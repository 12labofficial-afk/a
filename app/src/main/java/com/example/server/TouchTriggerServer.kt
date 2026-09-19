package com.example.server

import android.util.Log
import com.example.model.TriggerLog
import com.example.service.TouchAccessibilityService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.URLDecoder
import java.nio.charset.StandardCharsets
import java.util.UUID

class TouchTriggerServer(
    var port: Int = 8080,
    var targetX: Float = 540f,
    var targetY: Float = 1200f,
    var tapDurationMs: Long = 30L
) {
    companion object {
        private const val TAG = "TouchTriggerServer"

        // Bail out of a stuck client read instead of blocking this connection's handler
        // coroutine forever on a client that sent a partial request and went silent.
        private const val CLIENT_SOCKET_TIMEOUT_MS = 5000
    }

    private var serverSocket: ServerSocket? = null
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var serverJob: Job? = null

    private val _logsFlow = MutableSharedFlow<TriggerLog>(extraBufferCapacity = 50)
    val logsFlow: SharedFlow<TriggerLog> = _logsFlow.asSharedFlow()

    @Volatile
    var isRunning: Boolean = false
        private set

    fun start(onStatusChange: ((Boolean, String) -> Unit)? = null) {
        if (isRunning) {
            onStatusChange?.invoke(true, "Server is already active on port $port")
            return
        }

        serverJob = scope.launch {
            try {
                serverSocket = ServerSocket().apply {
                    reuseAddress = true
                    bind(InetSocketAddress("0.0.0.0", port))
                }
                isRunning = true
                Log.i(TAG, "TouchTriggerServer started on port $port")
                withContext(Dispatchers.Main) {
                    onStatusChange?.invoke(true, "Server listening on port $port")
                }

                while (isActive && isRunning) {
                    try {
                        val clientSocket = serverSocket?.accept() ?: break
                        clientSocket.tcpNoDelay = true
                        launch {
                            handleClient(clientSocket)
                        }
                    } catch (e: Exception) {
                        if (isRunning) {
                            Log.w(TAG, "Exception in server accept: ${e.localizedMessage}")
                        }
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to start server on port $port", e)
                isRunning = false
                withContext(Dispatchers.Main) {
                    onStatusChange?.invoke(false, "Error: ${e.localizedMessage}")
                }
            }
        }
    }

    fun stop(onStatusChange: ((Boolean, String) -> Unit)? = null) {
        isRunning = false
        try {
            serverSocket?.close()
            serverSocket = null
            serverJob?.cancel()
            serverJob = null
            Log.i(TAG, "TouchTriggerServer stopped")
            onStatusChange?.invoke(false, "Server stopped")
        } catch (e: Exception) {
            Log.e(TAG, "Error stopping server", e)
            onStatusChange?.invoke(false, "Error stopping: ${e.localizedMessage}")
        }
    }

    private suspend fun handleClient(socket: Socket) {
        val startTime = System.currentTimeMillis()
        val clientIp = socket.inetAddress?.hostAddress ?: "Unknown"

        try {
            socket.soTimeout = CLIENT_SOCKET_TIMEOUT_MS
            val reader = BufferedReader(InputStreamReader(socket.getInputStream(), StandardCharsets.UTF_8))
            val requestLine = reader.readLine()

            if (requestLine.isNullOrBlank()) {
                socket.close()
                return
            }

            // e.g., "GET /trigger HTTP/1.1" or "POST /tap?x=500&y=1000 HTTP/1.1"
            val parts = requestLine.split(" ")
            if (parts.size < 2) {
                sendResponse(socket.getOutputStream(), 400, "Bad Request", """{"error":"Invalid HTTP request"}""")
                socket.close()
                return
            }

            val rawUri = parts[1]
            val path = rawUri.substringBefore("?")
            val queryString = if (rawUri.contains("?")) rawUri.substringAfter("?") else ""
            val queryParams = parseQueryParams(queryString)

            when (path) {
                "/trigger", "/tap" -> {
                    val x = queryParams["x"]?.toFloatOrNull() ?: targetX
                    val y = queryParams["y"]?.toFloatOrNull() ?: targetY
                    val duration = queryParams["duration"]?.toLongOrNull() ?: tapDurationMs
                    // e.g. "?delay=5" -> tap fires 5s after this request, giving time to
                    // switch to the target app and watch "Show taps" to confirm it landed.
                    // No delay param -> fires immediately, same as before.
                    val delaySeconds = queryParams["delay"]?.toFloatOrNull()?.coerceIn(0f, 300f) ?: 0f

                    if (delaySeconds > 0f) {
                        scheduleDelayedTap(x, y, duration, delaySeconds)
                        val responseJson = """
                            {
                                "success": true,
                                "scheduled": true,
                                "delay_seconds": $delaySeconds,
                                "x": $x,
                                "y": $y,
                                "message": "Tap scheduled in ${delaySeconds}s"
                            }
                        """.trimIndent()
                        sendResponse(socket.getOutputStream(), 200, "OK", responseJson)
                    } else {
                        executeTapAndRespond(socket, startTime, clientIp, x, y, duration)
                    }
                }

                "/ping" -> {
                    val latency = System.currentTimeMillis() - startTime
                    val responseJson = """{"status":"pong","latency_ms":$latency,"time":${System.currentTimeMillis()}}"""
                    sendResponse(socket.getOutputStream(), 200, "OK", responseJson)
                }

                "/status" -> {
                    val isAccessibility = TouchAccessibilityService.instance != null
                    val responseJson = """
                        {
                            "status": "running",
                            "target_x": $targetX,
                            "target_y": $targetY,
                            "tap_duration_ms": $tapDurationMs,
                            "accessibility_ready": $isAccessibility
                        }
                    """.trimIndent()
                    sendResponse(socket.getOutputStream(), 200, "OK", responseJson)
                }

                else -> {
                    // Root or informational endpoint
                    val isAccessibility = TouchAccessibilityService.instance != null
                    val infoJson = """
                        {
                            "app": "Touch Trigger",
                            "status": "online",
                            "current_target": {"x": $targetX, "y": $targetY},
                            "accessibility_active": $isAccessibility,
                            "endpoints": {
                                "trigger": "/trigger (tap at preset x, y)",
                                "tap": "/tap?x={x}&y={y} (tap at custom coordinates)",
                                "status": "/status (view server & accessibility status)",
                                "ping": "/ping (measure response time)"
                            },
                            "termux_example": "curl -s http://${socket.localAddress.hostAddress}:$port/trigger"
                        }
                    """.trimIndent()
                    sendResponse(socket.getOutputStream(), 200, "OK", infoJson)
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error handling client request", e)
        } finally {
            try {
                socket.close()
            } catch (_: Exception) {}
        }
    }

    private suspend fun executeTapAndRespond(
        socket: Socket,
        startTime: Long,
        clientIp: String,
        x: Float,
        y: Float,
        duration: Long
    ) {
        val isServiceAvailable = TouchAccessibilityService.instance != null
        if (!isServiceAvailable) {
            val latency = System.currentTimeMillis() - startTime
            val errorJson = """
                {
                    "success": false,
                    "error": "Accessibility service is not active on target phone. Enable it in Settings.",
                    "latency_ms": $latency
                }
            """.trimIndent()
            sendResponse(socket.getOutputStream(), 503, "Service Unavailable", errorJson)

            val log = TriggerLog(
                id = UUID.randomUUID().toString(),
                timestamp = System.currentTimeMillis(),
                clientIp = clientIp,
                x = x,
                y = y,
                isSuccess = false,
                latencyMs = latency,
                message = "Failed: Accessibility Service not enabled"
            )
            _logsFlow.emit(log)
            return
        }

        com.example.service.FloatingPointerService.notifyTriggerDispatched()

        TouchAccessibilityService.performTap(x, y, duration) { success, message ->
            scope.launch {
                val latency = System.currentTimeMillis() - startTime
                val log = TriggerLog(
                    id = UUID.randomUUID().toString(),
                    timestamp = System.currentTimeMillis(),
                    clientIp = clientIp,
                    x = x,
                    y = y,
                    isSuccess = success,
                    latencyMs = latency,
                    message = message
                )
                _logsFlow.emit(log)
            }
        }

        // Send rapid response back to Termux client without waiting for gesture callback to minimize network latency
        val latency = System.currentTimeMillis() - startTime
        val successJson = """
            {
                "success": true,
                "x": $x,
                "y": $y,
                "duration_ms": $duration,
                "latency_ms": $latency,
                "message": "Touch command dispatched"
            }
        """.trimIndent()
        sendResponse(socket.getOutputStream(), 200, "OK", successJson)
    }

    /** Waits [delaySeconds] then dispatches the tap without an HTTP response to wait on -
     * the client already got its "scheduled" reply, so this only logs the outcome. */
    private fun scheduleDelayedTap(x: Float, y: Float, duration: Long, delaySeconds: Float) {
        scope.launch {
            delay((delaySeconds * 1000).toLong())

            val isServiceAvailable = TouchAccessibilityService.instance != null
            if (!isServiceAvailable) {
                _logsFlow.emit(
                    TriggerLog(
                        id = UUID.randomUUID().toString(),
                        timestamp = System.currentTimeMillis(),
                        clientIp = "Scheduled (${delaySeconds}s)",
                        x = x,
                        y = y,
                        isSuccess = false,
                        latencyMs = (delaySeconds * 1000).toLong(),
                        message = "Failed: Accessibility Service not enabled"
                    )
                )
                return@launch
            }

            com.example.service.FloatingPointerService.notifyTriggerDispatched()
            TouchAccessibilityService.performTap(x, y, duration) { success, message ->
                scope.launch {
                    _logsFlow.emit(
                        TriggerLog(
                            id = UUID.randomUUID().toString(),
                            timestamp = System.currentTimeMillis(),
                            clientIp = "Scheduled (${delaySeconds}s)",
                            x = x,
                            y = y,
                            isSuccess = success,
                            latencyMs = (delaySeconds * 1000).toLong(),
                            message = message
                        )
                    )
                }
            }
        }
    }

    private fun parseQueryParams(queryString: String): Map<String, String> {
        if (queryString.isBlank()) return emptyMap()
        val result = mutableMapOf<String, String>()
        for (pair in queryString.split("&")) {
            val idx = pair.indexOf("=")
            if (idx > 0) {
                val key = URLDecoder.decode(pair.substring(0, idx), "UTF-8")
                val value = URLDecoder.decode(pair.substring(idx + 1), "UTF-8")
                result[key] = value
            }
        }
        return result
    }

    private fun sendResponse(output: OutputStream, statusCode: Int, statusText: String, body: String) {
        val bodyBytes = body.toByteArray(StandardCharsets.UTF_8)
        val headers = "HTTP/1.1 $statusCode $statusText\r\n" +
                "Content-Type: application/json; charset=UTF-8\r\n" +
                "Content-Length: ${bodyBytes.size}\r\n" +
                "Connection: close\r\n\r\n"

        output.write(headers.toByteArray(StandardCharsets.UTF_8))
        output.write(bodyBytes)
        output.flush()
    }
}
