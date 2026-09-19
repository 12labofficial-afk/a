package com.example.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import com.example.MainActivity
import com.example.R
import com.example.server.TouchTriggerServer
import com.example.util.DiagLog
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class TriggerForegroundService : Service() {

    companion object {
        private const val TAG = "TriggerService"
        const val CHANNEL_ID = "touch_trigger_service_channel"
        const val NOTIFICATION_ID = 101

        const val ACTION_START = "com.example.service.ACTION_START"
        const val ACTION_STOP = "com.example.service.ACTION_STOP"
        const val ACTION_UPDATE_CONFIG = "com.example.service.ACTION_UPDATE_CONFIG"

        const val EXTRA_PORT = "extra_port"
        const val EXTRA_TARGET_X = "extra_target_x"
        const val EXTRA_TARGET_Y = "extra_target_y"
        const val EXTRA_DURATION = "extra_duration"

        private val _isServiceRunning = MutableStateFlow(false)
        val isServiceRunning: StateFlow<Boolean> = _isServiceRunning.asStateFlow()

        var serverInstance: TouchTriggerServer? = null
            private set

        fun startService(context: Context, port: Int, targetX: Float, targetY: Float, duration: Long) {
            val intent = Intent(context, TriggerForegroundService::class.java).apply {
                action = ACTION_START
                putExtra(EXTRA_PORT, port)
                putExtra(EXTRA_TARGET_X, targetX)
                putExtra(EXTRA_TARGET_Y, targetY)
                putExtra(EXTRA_DURATION, duration)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stopService(context: Context) {
            val intent = Intent(context, TriggerForegroundService::class.java).apply {
                action = ACTION_STOP
            }
            context.startService(intent)
        }

        fun updateCoordinates(targetX: Float, targetY: Float, duration: Long) {
            serverInstance?.let {
                it.targetX = targetX
                it.targetY = targetY
                it.tapDurationMs = duration
            }
        }

        /** Updates only the target position, leaving the configured tap duration untouched. */
        fun updateTargetPosition(targetX: Float, targetY: Float) {
            serverInstance?.let {
                it.targetX = targetX
                it.targetY = targetY
            }
        }
    }

    private var wakeLock: PowerManager.WakeLock? = null
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        DiagLog.init(this)
        DiagLog.log("TriggerForegroundService onCreate  pid=${android.os.Process.myPid()}")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        DiagLog.log("TriggerForegroundService onStartCommand  action=${intent?.action}")
        when (intent?.action) {
            ACTION_STOP -> {
                stopServerAndSelf()
                return START_NOT_STICKY
            }

            ACTION_UPDATE_CONFIG -> {
                val x = intent.getFloatExtra(EXTRA_TARGET_X, serverInstance?.targetX ?: 540f)
                val y = intent.getFloatExtra(EXTRA_TARGET_Y, serverInstance?.targetY ?: 1200f)
                val duration = intent.getLongExtra(EXTRA_DURATION, serverInstance?.tapDurationMs ?: 10L)
                updateCoordinates(x, y, duration)
            }

            ACTION_START, null -> {
                val port = intent?.getIntExtra(EXTRA_PORT, 8080) ?: 8080
                val targetX = intent?.getFloatExtra(EXTRA_TARGET_X, 540f) ?: 540f
                val targetY = intent?.getFloatExtra(EXTRA_TARGET_Y, 1200f) ?: 1200f
                val duration = intent?.getLongExtra(EXTRA_DURATION, 10L) ?: 10L

                startForeground(NOTIFICATION_ID, buildNotification("Listening on port $port..."))
                acquireLocks()
                startServer(port, targetX, targetY, duration)
            }
        }

        return START_STICKY
    }

    private fun startServer(port: Int, targetX: Float, targetY: Float, duration: Long) {
        if (serverInstance == null) {
            serverInstance = TouchTriggerServer(
                port = port,
                targetX = targetX,
                targetY = targetY,
                tapDurationMs = duration
            )
        } else {
            serverInstance?.port = port
            serverInstance?.targetX = targetX
            serverInstance?.targetY = targetY
            serverInstance?.tapDurationMs = duration
        }

        serverInstance?.start { started, message ->
            _isServiceRunning.value = started
            if (started) {
                updateNotification("Ready: Trigger listening on port $port")
            } else {
                updateNotification("Stopped: $message")
            }
        }
        _isServiceRunning.value = true
    }

    private fun stopServerAndSelf() {
        serverInstance?.stop()
        serverInstance = null
        releaseLocks()
        _isServiceRunning.value = false
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun acquireLocks() {
        try {
            // No WifiLock: the server only serves plain local sockets (loopback or LAN),
            // which doesn't need WIFI_MODE_FULL_HIGH_PERF and was just draining battery.
            val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = powerManager.newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK,
                "TouchTrigger::ServerWakeLock"
            ).apply {
                setReferenceCounted(false)
                // Held only for as long as the foreground service is alive; released in
                // releaseLocks() on stop/destroy, so no arbitrary timeout is needed.
                acquire()
            }
        } catch (e: Exception) {
            Log.w(TAG, "Could not acquire locks: ${e.localizedMessage}")
        }
    }

    private fun releaseLocks() {
        try {
            wakeLock?.let {
                if (it.isHeld) it.release()
            }
            wakeLock = null
        } catch (e: Exception) {
            Log.w(TAG, "Error releasing locks: ${e.localizedMessage}")
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                getString(R.string.channel_name),
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = getString(R.string.channel_description)
                setShowBadge(false)
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager?.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(statusText: String): Notification {
        val launchIntent = Intent(this, MainActivity::class.java)
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            launchIntent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        val stopIntent = Intent(this, TriggerForegroundService::class.java).apply {
            action = ACTION_STOP
        }
        val stopPendingIntent = PendingIntent.getService(
            this,
            1,
            stopIntent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Touch Trigger Active")
            .setContentText(statusText)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .addAction(android.R.drawable.ic_menu_close_clear_cancel, "Stop Server", stopPendingIntent)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    private fun updateNotification(statusText: String) {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(NOTIFICATION_ID, buildNotification(statusText))
    }

    override fun onDestroy() {
        DiagLog.log("TriggerForegroundService onDestroy  pid=${android.os.Process.myPid()}")
        stopServerAndSelf()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
