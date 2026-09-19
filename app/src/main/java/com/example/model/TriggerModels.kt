package com.example.model

data class TriggerTarget(
    val x: Float = 540f,
    val y: Float = 1200f,
    val durationMs: Long = 30L
)

data class TriggerLog(
    val id: String,
    val timestamp: Long,
    val clientIp: String,
    val x: Float,
    val y: Float,
    val isSuccess: Boolean,
    val latencyMs: Long,
    val message: String
)

data class ServerState(
    val isRunning: Boolean = false,
    val ipAddress: String = "127.0.0.1",
    val port: Int = 8080,
    val isAccessibilityActive: Boolean = false,
    val totalTriggersCount: Int = 0,
    val lastTriggerTime: Long? = null
)
