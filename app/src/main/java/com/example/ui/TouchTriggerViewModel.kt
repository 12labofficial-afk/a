package com.example.ui

import android.app.Application
import android.content.Context
import android.content.Intent
import android.os.PowerManager
import android.provider.Settings
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.example.model.TriggerLog
import com.example.service.TouchAccessibilityService
import com.example.service.TriggerForegroundService
import com.example.util.DiagLog
import com.example.util.NetworkUtils
import com.example.util.TouchTriggerPrefs
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.util.UUID

data class UiState(
    val ipAddress: String = "127.0.0.1",
    val networkInterface: String = "Detecting...",
    val isNetworkConnected: Boolean = false,
    val port: Int = 8080,
    val targetX: Float = 540f,
    val targetY: Float = 1200f,
    val durationMs: Long = 10L,
    val isServerRunning: Boolean = false,
    val isAccessibilityEnabled: Boolean = false,
    val isOverlayPermissionGranted: Boolean = false,
    val isIgnoringBatteryOptimizations: Boolean = false,
    val isFloatingPointerVisible: Boolean = false,
    val screenWidthPx: Int = 1080,
    val screenHeightPx: Int = 2400,
    val logs: List<TriggerLog> = emptyList(),
    val isPositionPickerOpen: Boolean = false,
    val feedbackMessage: String? = null,
    val lastExecutionTimeMs: Long? = null
)

class TouchTriggerViewModel(application: Application) : AndroidViewModel(application) {

    private val _uiState = MutableStateFlow(UiState())
    val uiState: StateFlow<UiState> = _uiState.asStateFlow()

    init {
        DiagLog.init(application)
        DiagLog.log("ViewModel init  pid=${android.os.Process.myPid()}")

        // Must happen before anything subscribes to FloatingPointerService.pointerCoordinates
        // below, otherwise that flow's still-default (540, 1200) value would immediately
        // overwrite the persisted target we're about to restore.
        com.example.service.FloatingPointerService.ensurePositionLoaded(application)

        // Read screen dimensions
        val displayMetrics = application.resources.displayMetrics
        val w = displayMetrics.widthPixels
        val h = displayMetrics.heightPixels

        // Restore the last-used position/duration/port instead of defaulting back to
        // screen center every time the process is restarted (the app being killed in
        // the background and relaunched is common - see the battery optimization card).
        val persistedPosition = TouchTriggerPrefs.loadPosition(application)
        val persistedDuration = TouchTriggerPrefs.loadDuration(application, 10L)
        val persistedPort = TouchTriggerPrefs.loadPort(application, 8080)

        _uiState.update {
            it.copy(
                screenWidthPx = w,
                screenHeightPx = h,
                targetX = persistedPosition?.first ?: (w / 2).toFloat(),
                targetY = persistedPosition?.second ?: (h / 2).toFloat(),
                durationMs = persistedDuration,
                port = persistedPort
            )
        }

        refreshNetworkInfo()
        checkAccessibilityStatus()
        checkOverlayPermission()
        checkBatteryOptimizationStatus()

        // Observe foreground service state
        viewModelScope.launch {
            TriggerForegroundService.isServiceRunning.collect { running ->
                _uiState.update { it.copy(isServerRunning = running) }
                if (running) {
                    observeServerLogs()
                }
            }
        }

        // Observe accessibility connection state
        viewModelScope.launch {
            TouchAccessibilityService.isServiceConnected.collect { connected ->
                DiagLog.log("Accessibility connected state changed: $connected")
                _uiState.update { it.copy(isAccessibilityEnabled = connected) }
            }
        }

        // Observe floating pointer visibility state
        viewModelScope.launch {
            com.example.service.FloatingPointerService.isPointerVisible.collect { visible ->
                _uiState.update { it.copy(isFloatingPointerVisible = visible) }
            }
        }

        // Observe floating pointer live coordinates
        viewModelScope.launch {
            com.example.service.FloatingPointerService.pointerCoordinates.collect { coords ->
                _uiState.update {
                    it.copy(targetX = coords.first, targetY = coords.second)
                }
            }
        }
    }

    fun checkOverlayPermission() {
        val granted = Settings.canDrawOverlays(getApplication())
        _uiState.update { it.copy(isOverlayPermissionGranted = granted) }
    }

    fun requestOverlayPermission(context: Context) {
        val intent = Intent(
            Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
            android.net.Uri.parse("package:${context.packageName}")
        ).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK
        }
        context.startActivity(intent)
    }

    /**
     * Whether the OS is currently allowed to background-kill this app to save power.
     * On OEM skins with aggressive app killers (MIUI, ColorOS, FuntouchOS, ...) this is
     * the single biggest reason the server/accessibility service stop working the moment
     * the user switches to another app - foreground services and wake locks alone don't
     * reliably survive it.
     */
    fun checkBatteryOptimizationStatus() {
        val context = getApplication<Application>()
        val powerManager = context.getSystemService(Context.POWER_SERVICE) as PowerManager
        val ignoring = powerManager.isIgnoringBatteryOptimizations(context.packageName)
        _uiState.update { it.copy(isIgnoringBatteryOptimizations = ignoring) }
    }

    fun requestIgnoreBatteryOptimizations(context: Context) {
        val intent = Intent(
            Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
            android.net.Uri.parse("package:${context.packageName}")
        ).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK
        }
        context.startActivity(intent)
    }

    fun toggleFloatingPointer(context: Context) {
        DiagLog.log("toggleFloatingPointer called  currentlyVisible=${_uiState.value.isFloatingPointerVisible}")
        checkOverlayPermission()
        if (!_uiState.value.isOverlayPermissionGranted) {
            requestOverlayPermission(context)
            _uiState.update { it.copy(feedbackMessage = "Please grant 'Display over other apps' permission") }
            return
        }

        val currentState = _uiState.value
        if (currentState.isFloatingPointerVisible) {
            com.example.service.FloatingPointerService.hide(context)
            _uiState.update { it.copy(feedbackMessage = "Floating pointer hidden") }
        } else {
            // Auto start background server if not already running
            if (!currentState.isServerRunning) {
                TriggerForegroundService.startService(
                    context = context,
                    port = currentState.port,
                    targetX = currentState.targetX,
                    targetY = currentState.targetY,
                    duration = currentState.durationMs
                )
            }
            com.example.service.FloatingPointerService.show(context)
            _uiState.update { it.copy(feedbackMessage = "Floating target active! Drag the small dark handle on its corner to move it.") }
        }
    }

    private fun observeServerLogs() {
        val server = TriggerForegroundService.serverInstance ?: return
        viewModelScope.launch {
            server.logsFlow.collect { newLog ->
                _uiState.update { state ->
                    val updated = (listOf(newLog) + state.logs).take(100)
                    state.copy(
                        logs = updated,
                        lastExecutionTimeMs = newLog.latencyMs,
                        feedbackMessage = if (newLog.isSuccess) {
                            "Executed in ${newLog.latencyMs} ms"
                        } else {
                            newLog.message
                        }
                    )
                }
            }
        }
    }

    fun refreshNetworkInfo() {
        val netInfo = NetworkUtils.getLocalIpAddress()
        _uiState.update {
            it.copy(
                ipAddress = netInfo.ipAddress,
                networkInterface = netInfo.interfaceName,
                isNetworkConnected = netInfo.isConnected
            )
        }
    }

    fun checkAccessibilityStatus() {
        val isEnabled = TouchAccessibilityService.instance != null ||
                TouchAccessibilityService.isAccessibilitySettingsOn(getApplication())
        _uiState.update { it.copy(isAccessibilityEnabled = isEnabled) }
    }

    fun openAccessibilitySettings(context: Context) {
        val intent = Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK
        }
        context.startActivity(intent)
    }

    /** Whether the floating pointer was showing right before the header switch turned
     * everything off, so turning it back on can restore it too. */
    private var pointerVisibleBeforeDisable = false

    /** Master on/off switch (header toggle): stops/starts the trigger server and, with
     * it, the floating pointer overlay - the whole app's active behavior in one flip. */
    fun toggleServer(context: Context) {
        val currentState = _uiState.value
        DiagLog.log("toggleServer called  currentlyRunning=${currentState.isServerRunning}")
        if (currentState.isServerRunning) {
            pointerVisibleBeforeDisable = currentState.isFloatingPointerVisible
            if (currentState.isFloatingPointerVisible) {
                com.example.service.FloatingPointerService.hide(context)
            }
            TriggerForegroundService.stopService(context)
            _uiState.update { it.copy(feedbackMessage = "Touch Trigger turned off") }
        } else {
            TriggerForegroundService.startService(
                context = context,
                port = currentState.port,
                targetX = currentState.targetX,
                targetY = currentState.targetY,
                duration = currentState.durationMs
            )
            observeServerLogs()
            if (pointerVisibleBeforeDisable) {
                com.example.service.FloatingPointerService.show(context)
            }
            _uiState.update { it.copy(feedbackMessage = "Touch Trigger turned on") }
        }
    }

    fun setTargetCoordinates(x: Float, y: Float) {
        val boundedX = x.coerceIn(0f, _uiState.value.screenWidthPx.toFloat())
        val boundedY = y.coerceIn(0f, _uiState.value.screenHeightPx.toFloat())

        _uiState.update {
            it.copy(targetX = boundedX, targetY = boundedY)
        }
        TriggerForegroundService.updateCoordinates(boundedX, boundedY, _uiState.value.durationMs)
        com.example.service.FloatingPointerService.setPosition(boundedX, boundedY)
        TouchTriggerPrefs.savePosition(getApplication(), boundedX, boundedY)
    }

    fun setPort(port: Int) {
        if (port in 1024..65535) {
            _uiState.update { it.copy(port = port) }
            TouchTriggerPrefs.savePort(getApplication(), port)
        }
    }

    fun setDuration(durationMs: Long) {
        // Android's own dispatchGesture needs a fraction of a frame to register a stroke
        // as a valid tap; going below ~1ms isn't meaningfully faster and some apps'
        // gesture detectors may simply drop touches that short, so 1ms is the floor.
        val duration = durationMs.coerceIn(1L, 1000L)
        _uiState.update { it.copy(durationMs = duration) }
        TriggerForegroundService.updateCoordinates(_uiState.value.targetX, _uiState.value.targetY, duration)
        TouchTriggerPrefs.saveDuration(getApplication(), duration)
    }

    fun testTap(context: Context) {
        val state = _uiState.value
        val startTime = System.currentTimeMillis()
        DiagLog.log("testTap called  target=(${state.targetX}, ${state.targetY})  duration=${state.durationMs}ms")

        com.example.service.FloatingPointerService.notifyTriggerDispatched()

        val dispatched = TouchAccessibilityService.performTap(
            x = state.targetX,
            y = state.targetY,
            durationMs = state.durationMs
        ) { success, message ->
            val latency = System.currentTimeMillis() - startTime
            val log = TriggerLog(
                id = UUID.randomUUID().toString(),
                timestamp = System.currentTimeMillis(),
                clientIp = "Manual Test",
                x = state.targetX,
                y = state.targetY,
                isSuccess = success,
                latencyMs = latency,
                message = message
            )
            _uiState.update {
                it.copy(
                    logs = (listOf(log) + it.logs).take(100),
                    lastExecutionTimeMs = latency,
                    feedbackMessage = if (success) "Executed in ${latency} ms" else message
                )
            }
        }

        if (!dispatched) {
            _uiState.update {
                it.copy(feedbackMessage = "Accessibility service is inactive. Please enable in Settings.")
            }
        }
    }

    fun openPositionPicker(open: Boolean) {
        _uiState.update { it.copy(isPositionPickerOpen = open) }
    }

    fun clearLogs() {
        _uiState.update { it.copy(logs = emptyList()) }
    }

    fun dismissFeedback() {
        _uiState.update { it.copy(feedbackMessage = null) }
    }
}
