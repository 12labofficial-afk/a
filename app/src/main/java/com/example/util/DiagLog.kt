package com.example.util

import android.content.Context
import android.content.SharedPreferences
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.text.SimpleDateFormat
import java.util.Locale

/**
 * In-app diagnostic log for the floating pointer's lifecycle. Exists because the person
 * running this app has no PC/adb to pull logcat from, so this surfaces the same kind of
 * information directly in the UI (see the Diagnostics card) to copy/paste for debugging.
 *
 * Persisted to disk on every write, not just kept in memory: the exact scenario this is
 * meant to catch - the process getting killed - would otherwise wipe the log the instant
 * it happens, right before the moment we actually need to see.
 */
object DiagLog {
    private const val PREFS_NAME = "touch_trigger_diag"
    private const val KEY_LOG = "log_lines"
    private const val MAX_LINES = 300

    private val _entries = MutableStateFlow<List<String>>(emptyList())
    val entries: StateFlow<List<String>> = _entries.asStateFlow()

    private var prefs: SharedPreferences? = null
    private val timeFormat = SimpleDateFormat("HH:mm:ss.SSS", Locale.US)

    @Synchronized
    fun init(context: Context) {
        if (prefs != null) return
        val p = context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs = p
        val saved = p.getString(KEY_LOG, null)
        if (!saved.isNullOrEmpty()) {
            _entries.value = saved.split("\n").filter { it.isNotBlank() }
        }
    }

    @Synchronized
    fun log(message: String) {
        val line = "${timeFormat.format(System.currentTimeMillis())}  $message"
        val updated = (listOf(line) + _entries.value).take(MAX_LINES)
        _entries.value = updated
        prefs?.edit()?.putString(KEY_LOG, updated.joinToString("\n"))?.apply()
    }

    @Synchronized
    fun clear() {
        _entries.value = emptyList()
        prefs?.edit()?.remove(KEY_LOG)?.apply()
    }
}
