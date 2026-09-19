package com.example.util

import android.content.Context
import java.util.UUID

/**
 * Per-install shared secret required by TouchTriggerServer to accept /trigger and /tap
 * requests. Without it, any device on the same Wi-Fi (or any webpage open in this phone's
 * own browser, since the server is reachable at 127.0.0.1 too) could fire arbitrary taps.
 */
object AuthToken {
    private const val PREFS_NAME = "touch_trigger_prefs"
    private const val KEY_TOKEN = "auth_token"

    fun getOrCreate(context: Context): String {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val existing = prefs.getString(KEY_TOKEN, null)
        if (!existing.isNullOrBlank()) return existing
        val token = UUID.randomUUID().toString().replace("-", "")
        prefs.edit().putString(KEY_TOKEN, token).apply()
        return token
    }
}
