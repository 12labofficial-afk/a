package com.example.util

import java.net.Inet4Address
import java.net.NetworkInterface

object NetworkUtils {

    data class NetworkInfo(
        val ipAddress: String,
        val interfaceName: String,
        val isConnected: Boolean
    )

    fun getLocalIpAddress(): NetworkInfo {
        try {
            val interfaces = NetworkInterface.getNetworkInterfaces()
            var fallbackIp: NetworkInfo? = null

            while (interfaces.hasMoreElements()) {
                val networkInterface = interfaces.nextElement()
                if (networkInterface.isLoopback || !networkInterface.isUp) continue

                val addresses = networkInterface.inetAddresses
                while (addresses.hasMoreElements()) {
                    val address = addresses.nextElement()
                    if (!address.isLoopbackAddress && address is Inet4Address) {
                        val hostAddress = address.hostAddress ?: continue
                        val name = networkInterface.displayName ?: networkInterface.name ?: "wlan"

                        // Prioritize Wi-Fi / Hotspot interfaces (wlan, ap, wlan0, ap0, etc.)
                        if (name.contains("wlan", ignoreCase = true) ||
                            name.contains("ap", ignoreCase = true) ||
                            name.contains("eth", ignoreCase = true)
                        ) {
                            return NetworkInfo(
                                ipAddress = hostAddress,
                                interfaceName = name,
                                isConnected = true
                            )
                        }

                        if (fallbackIp == null) {
                            fallbackIp = NetworkInfo(
                                ipAddress = hostAddress,
                                interfaceName = name,
                                isConnected = true
                            )
                        }
                    }
                }
            }

            if (fallbackIp != null) {
                return fallbackIp
            }
        } catch (_: Exception) {}

        return NetworkInfo(
            ipAddress = "127.0.0.1",
            interfaceName = "Loopback",
            isConnected = false
        )
    }
}
