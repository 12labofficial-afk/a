package com.example.util

import android.content.Context

/** Persists the last-used target position/duration/port so the app doesn't
 * forget them across process restarts (the app is only killed and relaunched
 * when the OS/OEM kills the background process - the in-memory state alone
 * doesn't survive that). */
object TouchTriggerPrefs {
    private const val PREFS_NAME = "touch_trigger_prefs"
    private const val KEY_X = "target_x"
    private const val KEY_Y = "target_y"
    private const val KEY_DURATION = "duration_ms"
    private const val KEY_PORT = "port"

    fun loadPosition(context: Context): Pair<Float, Float>? {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        if (!prefs.contains(KEY_X) || !prefs.contains(KEY_Y)) return null
        return Pair(prefs.getFloat(KEY_X, 0f), prefs.getFloat(KEY_Y, 0f))
    }

    fun savePosition(context: Context, x: Float, y: Float) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
            .putFloat(KEY_X, x)
            .putFloat(KEY_Y, y)
            .apply()
    }

    fun loadDuration(context: Context, default: Long): Long =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).getLong(KEY_DURATION, default)

    fun saveDuration(context: Context, duration: Long) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
            .putLong(KEY_DURATION, duration)
            .apply()
    }

    fun loadPort(context: Context, default: Int): Int =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).getInt(KEY_PORT, default)

    fun savePort(context: Context, port: Int) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
            .putInt(KEY_PORT, port)
            .apply()
    }
}
