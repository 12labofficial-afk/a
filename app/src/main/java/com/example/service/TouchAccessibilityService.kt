package com.example.service

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Context
import android.graphics.Path
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.TextUtils
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

class TouchAccessibilityService : AccessibilityService() {

    companion object {
        private const val TAG = "TouchAccessService"
        
        private val _isServiceConnected = MutableStateFlow(false)
        val isServiceConnected: StateFlow<Boolean> = _isServiceConnected.asStateFlow()

        @Volatile
        var instance: TouchAccessibilityService? = null
            private set

        fun isAccessibilitySettingsOn(context: Context): Boolean {
            val expectedServiceName = "${context.packageName}/${TouchAccessibilityService::class.java.canonicalName}"
            try {
                val enabledServices = Settings.Secure.getString(
                    context.contentResolver,
                    Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
                ) ?: return false

                val colonSplitter = TextUtils.SimpleStringSplitter(':')
                colonSplitter.setString(enabledServices)
                while (colonSplitter.hasNext()) {
                    val componentName = colonSplitter.next()
                    if (componentName.equals(expectedServiceName, ignoreCase = true) ||
                        componentName.contains(TouchAccessibilityService::class.java.simpleName)
                    ) {
                        return true
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Error checking accessibility settings", e)
            }
            return false
        }

        fun performTap(
            x: Float,
            y: Float,
            durationMs: Long = 50L,
            onResult: ((Boolean, String) -> Unit)? = null
        ): Boolean {
            val currentInstance = instance
            if (currentInstance == null) {
                onResult?.invoke(false, "Accessibility Service is not running. Enable it in Settings.")
                return false
            }

            return try {
                val path = Path().apply {
                    moveTo(x, y)
                }
                val strokeDuration = durationMs.coerceIn(1L, 100L)
                val stroke = GestureDescription.StrokeDescription(path, 0L, strokeDuration)
                val gesture = GestureDescription.Builder().addStroke(stroke).build()

                val dispatched = currentInstance.dispatchGesture(
                    gesture,
                    object : GestureResultCallback() {
                        override fun onCompleted(gestureDescription: GestureDescription?) {
                            Log.d(TAG, "Touch gesture completed successfully at ($x, $y)")
                            onResult?.invoke(true, "Tap successfully executed at (${x.toInt()}, ${y.toInt()})")
                        }

                        override fun onCancelled(gestureDescription: GestureDescription?) {
                            Log.w(TAG, "Touch gesture cancelled by system at ($x, $y)")
                            onResult?.invoke(false, "Tap cancelled by system at (${x.toInt()}, ${y.toInt()})")
                        }
                    },
                    Handler(Looper.getMainLooper())
                )

                if (!dispatched) {
                    onResult?.invoke(false, "Failed to dispatch gesture to system")
                }
                dispatched
            } catch (e: Exception) {
                Log.e(TAG, "Error dispatching gesture", e)
                onResult?.invoke(false, "Exception during gesture: ${e.localizedMessage}")
                false
            }
        }
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        _isServiceConnected.value = true
        Log.i(TAG, "TouchAccessibilityService connected successfully")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // No event consumption required - service solely dispatches configured touch gestures
    }

    override fun onInterrupt() {
        Log.w(TAG, "TouchAccessibilityService interrupted")
    }

    override fun onDestroy() {
        super.onDestroy()
        if (instance == this) {
            instance = null
            _isServiceConnected.value = false
        }
        Log.i(TAG, "TouchAccessibilityService destroyed")
    }
}
