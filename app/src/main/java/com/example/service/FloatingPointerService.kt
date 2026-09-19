package com.example.service

import android.animation.ValueAnimator
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.PixelFormat
import android.os.Build
import android.os.IBinder
import android.provider.Settings
import android.util.Log
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.example.util.TouchTriggerPrefs
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class FloatingPointerService : Service() {

    companion object {
        private const val TAG = "FloatingPointerService"
        const val ACTION_SHOW = "com.example.service.ACTION_SHOW_POINTER"
        const val ACTION_HIDE = "com.example.service.ACTION_HIDE_POINTER"
        private const val NOTIFICATION_ID = 102
        private const val CHANNEL_ID = "touch_trigger_pointer_channel"
        private const val WATCHDOG_INTERVAL_MS = 3000L

        private val _isPointerVisible = MutableStateFlow(false)
        val isPointerVisible: StateFlow<Boolean> = _isPointerVisible.asStateFlow()

        private val _pointerCoordinates = MutableStateFlow(Pair(540f, 1200f))
        val pointerCoordinates: StateFlow<Pair<Float, Float>> = _pointerCoordinates.asStateFlow()

        private var hasUserSetPosition = false
        private var savedX = 540f
        private var savedY = 1200f
        private var loadedPersistedPosition = false

        var activePointerView: PointerOverlayView? = null
            private set

        var instance: FloatingPointerService? = null
            private set

        /**
         * Loads the persisted target position into pointerCoordinates before anything
         * (the ViewModel included) reads or subscribes to it, so a cold process start
         * doesn't briefly - or permanently, if nothing else updates it first - show the
         * hardcoded (540, 1200) default instead of where the user actually left it.
         */
        fun ensurePositionLoaded(context: Context) {
            if (loadedPersistedPosition) return
            loadedPersistedPosition = true
            val saved = TouchTriggerPrefs.loadPosition(context) ?: return
            hasUserSetPosition = true
            savedX = saved.first
            savedY = saved.second
            _pointerCoordinates.value = saved
        }

        /**
         * The crosshair window is FLAG_NOT_TOUCHABLE (touches always pass through to the
         * app underneath - see showPointer()), so this is how PositionPickerDialog moves
         * it. After the layout pass we read back the window's real on-screen location
         * instead of trusting our own math, so the reported target coordinates always
         * match where dispatchGesture will actually land.
         */
        fun setPosition(x: Float, y: Float) {
            hasUserSetPosition = true
            savedX = x
            savedY = y
            _pointerCoordinates.value = Pair(x, y)
            TriggerForegroundService.updateTargetPosition(x, y)

            val service = instance ?: return
            val lp = service.windowLayoutParams ?: return
            val v = service.pointerView ?: return
            val size = v.width.takeIf { it > 0 } ?: (44 * service.resources.displayMetrics.density).toInt()
            lp.x = (x - size / 2f).toInt()
            lp.y = (y - size / 2f).toInt()
            try {
                service.windowManager?.updateViewLayout(v, lp)
            } catch (_: Exception) {}
            service.repositionHandle()
            v.post { service.reportActualPosition(v) }
        }

        fun show(context: Context) {
            if (!Settings.canDrawOverlays(context)) return
            ensurePositionLoaded(context)
            val intent = Intent(context, FloatingPointerService::class.java).apply {
                action = ACTION_SHOW
            }
            // Started as a foreground service (see onStartCommand) so OEM background-app
            // killers (MIUI, ColorOS, FuntouchOS, ...) don't reclaim it - and with it the
            // whole process, including the accessibility service - a few seconds after the
            // user switches away to the app they actually want to tap in.
            ContextCompat.startForegroundService(context, intent)
        }

        fun hide(context: Context) {
            val intent = Intent(context, FloatingPointerService::class.java).apply {
                action = ACTION_HIDE
            }
            context.startService(intent)
        }

        fun notifyTriggerDispatched() {
            activePointerView?.post {
                activePointerView?.playTriggerPulse()
            }
        }
    }

    private var windowManager: WindowManager? = null
    private var pointerView: PointerOverlayView? = null
    private var windowLayoutParams: WindowManager.LayoutParams? = null
    private var handleView: DragHandleView? = null
    private var handleLayoutParams: WindowManager.LayoutParams? = null
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var watchdogJob: Job? = null

    override fun onCreate() {
        super.onCreate()
        instance = this
        windowManager = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        createNotificationChannel()
        ensurePositionLoaded(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_HIDE -> {
                removePointer()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
            ACTION_SHOW, null -> {
                if (!Settings.canDrawOverlays(this)) {
                    Log.w(TAG, "Cannot draw overlays: Permission not granted")
                    stopSelf()
                } else {
                    startForeground(NOTIFICATION_ID, buildNotification())
                    showPointer()
                }
            }
        }
        return START_NOT_STICKY
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Floating Pointer",
                NotificationManager.IMPORTANCE_MIN
            ).apply {
                description = "Shows while the floating touch target overlay is active"
                setShowBadge(false)
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager?.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Touch Trigger pointer active")
            .setContentText("Floating target overlay is showing")
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .build()
    }

    private fun showPointer() {
        if (pointerView != null) return

        val displayMetrics = resources.displayMetrics
        val screenWidth = displayMetrics.widthPixels
        val screenHeight = displayMetrics.heightPixels

        val viewSizePx = (44 * displayMetrics.density).toInt()

        val layoutType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            @Suppress("DEPRECATION")
            WindowManager.LayoutParams.TYPE_PHONE
        }

        val startScreenX = if (hasUserSetPosition) {
            (savedX - viewSizePx / 2f).toInt()
        } else {
            (screenWidth - viewSizePx) / 2
        }
        val startScreenY = if (hasUserSetPosition) {
            (savedY - viewSizePx / 2f).toInt()
        } else {
            (screenHeight - viewSizePx) / 2
        }

        val params = WindowManager.LayoutParams(
            viewSizePx,
            viewSizePx,
            layoutType,
            // Purely visual crosshair overlay: it must NEVER intercept touches, or every
            // tap dispatched under it (and every real user tap) would be swallowed by this
            // window instead of reaching the app underneath. Moving it is done through the
            // separate small drag handle below instead.
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                    WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                    WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = startScreenX
            y = startScreenY
        }
        windowLayoutParams = params

        val overlayView = PointerOverlayView(this)
        pointerView = overlayView

        try {
            windowManager?.addView(overlayView, params)
            activePointerView = overlayView
            _isPointerVisible.value = true
            overlayView.post { reportActualPosition(overlayView) }
            addDragHandle(viewSizePx, startScreenX, startScreenY, displayMetrics.density)
            startWatchdog()
        } catch (e: Exception) {
            Log.e(TAG, "Error adding pointer view", e)
        }
    }

    /**
     * Small touchable handle badge attached to the crosshair's corner - this is what
     * actually receives drag gestures, since the crosshair itself must stay
     * FLAG_NOT_TOUCHABLE (see showPointer()).
     */
    private fun addDragHandle(mainSizePx: Int, mainScreenX: Int, mainScreenY: Int, density: Float) {
        val handleSizePx = (26 * density).toInt()
        val layoutType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            @Suppress("DEPRECATION")
            WindowManager.LayoutParams.TYPE_PHONE
        }

        val params = WindowManager.LayoutParams(
            handleSizePx,
            handleSizePx,
            layoutType,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                    WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = mainScreenX + mainSizePx - handleSizePx / 2
            y = mainScreenY + mainSizePx - handleSizePx / 2
        }
        handleLayoutParams = params

        val handle = DragHandleView(this)
        handle.setOnTouchListener(object : View.OnTouchListener {
            private var touchDownRawX = 0f
            private var touchDownRawY = 0f
            private var startMainX = 0
            private var startMainY = 0
            private var startHandleX = 0
            private var startHandleY = 0

            override fun onTouch(v: View?, event: MotionEvent?): Boolean {
                val mainLp = windowLayoutParams ?: return false
                val handleLp = handleLayoutParams ?: return false
                val mainView = pointerView ?: return false
                when (event?.action) {
                    MotionEvent.ACTION_DOWN -> {
                        touchDownRawX = event.rawX
                        touchDownRawY = event.rawY
                        startMainX = mainLp.x
                        startMainY = mainLp.y
                        startHandleX = handleLp.x
                        startHandleY = handleLp.y
                        return true
                    }
                    MotionEvent.ACTION_MOVE -> {
                        val dx = (event.rawX - touchDownRawX).toInt()
                        val dy = (event.rawY - touchDownRawY).toInt()
                        mainLp.x = startMainX + dx
                        mainLp.y = startMainY + dy
                        handleLp.x = startHandleX + dx
                        handleLp.y = startHandleY + dy
                        try {
                            windowManager?.updateViewLayout(mainView, mainLp)
                            windowManager?.updateViewLayout(v, handleLp)
                        } catch (_: Exception) {}
                        return true
                    }
                    MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                        mainView.post { reportActualPosition(mainView) }
                        return true
                    }
                }
                return false
            }
        })
        handleView = handle

        try {
            windowManager?.addView(handle, params)
        } catch (e: Exception) {
            Log.e(TAG, "Error adding drag handle", e)
        }
    }

    private fun repositionHandle() {
        val mainLp = windowLayoutParams ?: return
        val handle = handleView ?: return
        val handleLp = handleLayoutParams ?: return
        val mainSizePx = (44 * resources.displayMetrics.density).toInt()
        val handleSizePx = handle.width.takeIf { it > 0 } ?: (26 * resources.displayMetrics.density).toInt()
        handleLp.x = mainLp.x + mainSizePx - handleSizePx / 2
        handleLp.y = mainLp.y + mainSizePx - handleSizePx / 2
        try {
            windowManager?.updateViewLayout(handle, handleLp)
        } catch (_: Exception) {}
    }

    /**
     * Some OEM skins silently tear down overlay windows in certain apps (secure/DRM
     * screens, aggressive per-app "floating window" toggles, etc.) without any callback.
     * Poll for that and re-add the views if it happens and the permission is still held,
     * instead of leaving the pointer permanently gone until the user re-opens the app.
     */
    private fun startWatchdog() {
        watchdogJob?.cancel()
        watchdogJob = serviceScope.launch {
            while (isActive) {
                delay(WATCHDOG_INTERVAL_MS)
                if (!Settings.canDrawOverlays(this@FloatingPointerService)) continue

                val view = pointerView
                val lp = windowLayoutParams
                if (view != null && lp != null && !view.isAttachedToWindow) {
                    try {
                        windowManager?.addView(view, lp)
                        Log.w(TAG, "Re-added pointer overlay after it was removed externally")
                    } catch (e: Exception) {
                        Log.e(TAG, "Failed to re-add pointer overlay", e)
                    }
                }

                val handle = handleView
                val handleLp = handleLayoutParams
                if (handle != null && handleLp != null && !handle.isAttachedToWindow) {
                    try {
                        windowManager?.addView(handle, handleLp)
                    } catch (e: Exception) {
                        Log.e(TAG, "Failed to re-add drag handle", e)
                    }
                }
            }
        }
    }

    /**
     * Reads the overlay's true on-screen position after layout (window-relative lp.x/y
     * alone can be off by a status bar / cutout inset) and publishes it as the tap target.
     */
    private fun reportActualPosition(view: PointerOverlayView) {
        if (!view.isAttachedToWindow) return
        val loc = IntArray(2)
        view.getLocationOnScreen(loc)
        val centerX = loc[0] + view.width / 2f
        val centerY = loc[1] + view.height / 2f
        hasUserSetPosition = true
        savedX = centerX
        savedY = centerY
        _pointerCoordinates.value = Pair(centerX, centerY)
        TriggerForegroundService.updateTargetPosition(centerX, centerY)
        TouchTriggerPrefs.savePosition(this, centerX, centerY)
        view.updateCoordinatesText(centerX.toInt(), centerY.toInt())
    }

    private fun removePointer() {
        watchdogJob?.cancel()
        watchdogJob = null

        val viewToRemove = pointerView
        pointerView = null
        activePointerView = null
        _isPointerVisible.value = false
        if (viewToRemove != null) {
            try {
                if (viewToRemove.isAttachedToWindow) {
                    windowManager?.removeViewImmediate(viewToRemove)
                } else {
                    windowManager?.removeView(viewToRemove)
                }
            } catch (e: Exception) {
                Log.e(TAG, "Error removing pointer view safely", e)
            }
        }

        val handleToRemove = handleView
        handleView = null
        if (handleToRemove != null) {
            try {
                if (handleToRemove.isAttachedToWindow) {
                    windowManager?.removeViewImmediate(handleToRemove)
                } else {
                    windowManager?.removeView(handleToRemove)
                }
            } catch (e: Exception) {
                Log.e(TAG, "Error removing drag handle safely", e)
            }
        }
    }

    override fun onDestroy() {
        removePointer()
        instance = null
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    /**
     * Small touchable badge used to drag the (non-touchable) crosshair around.
     */
    class DragHandleView(context: Context) : View(context) {
        private val backgroundPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.FILL
            color = Color.parseColor("#DD263238")
        }

        private val borderPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeWidth = 2f
            color = Color.WHITE
        }

        private val glyphPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeWidth = 2.5f
            strokeCap = Paint.Cap.ROUND
            color = Color.WHITE
        }

        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            val cx = width / 2f
            val cy = height / 2f
            val r = (width.coerceAtMost(height) / 2f) - 2f

            canvas.drawCircle(cx, cy, r, backgroundPaint)
            canvas.drawCircle(cx, cy, r, borderPaint)

            // Simple 4-way cross to signal "drag to move"
            val len = r * 0.55f
            canvas.drawLine(cx - len, cy, cx + len, cy, glyphPaint)
            canvas.drawLine(cx, cy - len, cx, cy + len, glyphPaint)
        }
    }

    /**
     * Custom drawing view for the floating crosshair target pointer
     */
    class PointerOverlayView(context: Context) : View(context) {

        private val outerRingPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeWidth = 2.5f
            color = Color.parseColor("#00E676")
        }

        private val innerRingPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeWidth = 1.5f
            color = Color.parseColor("#80FFFFFF")
        }

        private val crosshairPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeWidth = 2f
            color = Color.parseColor("#00E676")
        }

        private val centerDotPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.FILL
            color = Color.parseColor("#FF1744")
        }

        private val pulsePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.FILL
            color = Color.parseColor("#66FF1744")
        }

        private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.WHITE
            textSize = 18f
            textAlign = Paint.Align.CENTER
            setShadowLayer(3f, 0f, 1f, Color.BLACK)
        }

        private var coordText = ""
        private var pulseRadius = 0f

        fun updateCoordinatesText(x: Int, y: Int) {
            coordText = "$x, $y"
            invalidate()
        }

        fun playTriggerPulse() {
            val maxRadius = width / 2f
            val animator = ValueAnimator.ofFloat(0f, maxRadius).apply {
                duration = 250L
                addUpdateListener { animation ->
                    pulseRadius = animation.animatedValue as Float
                    val alpha = ((1f - (pulseRadius / maxRadius)) * 180).toInt()
                    pulsePaint.alpha = alpha.coerceIn(0, 255)
                    invalidate()
                }
            }
            animator.start()
        }

        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            val cx = width / 2f
            val cy = height / 2f
            val baseRadius = (width.coerceAtMost(height) / 2f) - 10f

            // Trigger Pulse ring
            if (pulseRadius > 0f) {
                canvas.drawCircle(cx, cy, pulseRadius, pulsePaint)
            }

            // Outer target circle
            canvas.drawCircle(cx, cy, baseRadius, outerRingPaint)
            // Inner target circle
            canvas.drawCircle(cx, cy, baseRadius * 0.5f, innerRingPaint)

            // Crosshairs
            val chLength = baseRadius * 0.35f
            // Vertical crosshair
            canvas.drawLine(cx, cy - baseRadius, cx, cy - baseRadius + chLength, crosshairPaint)
            canvas.drawLine(cx, cy + baseRadius - chLength, cx, cy + baseRadius, crosshairPaint)
            // Horizontal crosshair
            canvas.drawLine(cx - baseRadius, cy, cx - baseRadius + chLength, cy, crosshairPaint)
            canvas.drawLine(cx + baseRadius - chLength, cy, cx + baseRadius, cy, crosshairPaint)

            // Center target bullseye dot
            canvas.drawCircle(cx, cy, 6f, centerDotPaint)

            // Coordinate label badge below center
            if (coordText.isNotEmpty()) {
                canvas.drawText(coordText, cx, cy + baseRadius + 4f, textPaint)
            }
        }
    }
}
