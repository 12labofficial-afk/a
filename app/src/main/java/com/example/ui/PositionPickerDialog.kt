package com.example.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties

@Composable
fun PositionPickerDialog(
    initialX: Float,
    initialY: Float,
    screenWidthPx: Int,
    screenHeightPx: Int,
    onDismiss: () -> Unit,
    onConfirm: (Float, Float) -> Unit
) {
    var currentX by remember { mutableFloatStateOf(initialX) }
    var currentY by remember { mutableFloatStateOf(initialY) }

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false)
    ) {
        Surface(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Black.copy(alpha = 0.92f)),
            color = Color.Transparent
        ) {
            Box(modifier = Modifier.fillMaxSize()) {
                // Interactive Touch Canvas
                Canvas(
                    modifier = Modifier
                        .fillMaxSize()
                        .testTag("position_picker_canvas")
                        .pointerInput(Unit) {
                            detectTapGestures { offset ->
                                // Map canvas touch directly to actual screen coordinates
                                currentX = offset.x
                                currentY = offset.y
                            }
                        }
                ) {
                    val w = size.width
                    val h = size.height

                    // Grid lines for visual precision
                    val gridColor = Color(0x33FFFFFF)
                    val step = 100f
                    var gx = step
                    while (gx < w) {
                        drawLine(
                            color = gridColor,
                            start = Offset(gx, 0f),
                            end = Offset(gx, h),
                            strokeWidth = 1f
                        )
                        gx += step
                    }
                    var gy = step
                    while (gy < h) {
                        drawLine(
                            color = gridColor,
                            start = Offset(0f, gy),
                            end = Offset(w, gy),
                            strokeWidth = 1f
                        )
                        gy += step
                    }

                    // Target Crosshairs
                    val targetColor = Color(0xFFFF5252)
                    drawLine(
                        color = targetColor.copy(alpha = 0.6f),
                        start = Offset(0f, currentY),
                        end = Offset(w, currentY),
                        strokeWidth = 2f
                    )
                    drawLine(
                        color = targetColor.copy(alpha = 0.6f),
                        start = Offset(currentX, 0f),
                        end = Offset(currentX, h),
                        strokeWidth = 2f
                    )

                    // Target concentric circles
                    drawCircle(
                        color = targetColor,
                        radius = 24f,
                        center = Offset(currentX, currentY),
                        style = Stroke(width = 4f)
                    )
                    drawCircle(
                        color = targetColor,
                        radius = 48f,
                        center = Offset(currentX, currentY),
                        style = Stroke(width = 2f)
                    )
                    drawCircle(
                        color = Color.White,
                        radius = 6f,
                        center = Offset(currentX, currentY)
                    )
                }

                // Header Control Card
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(16.dp)
                        .align(Alignment.TopCenter),
                    shape = RoundedCornerShape(16.dp),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.95f)
                    )
                ) {
                    Column(
                        modifier = Modifier.padding(16.dp),
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(
                                text = "Tap Anywhere to Set Target",
                                style = MaterialTheme.typography.titleMedium
                            )
                            IconButton(onClick = onDismiss) {
                                Icon(Icons.Default.Close, contentDescription = "Close Picker")
                            }
                        }

                        Spacer(modifier = Modifier.height(8.dp))

                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceEvenly
                        ) {
                            Text(
                                text = "X: ${currentX.toInt()} px",
                                style = MaterialTheme.typography.bodyLarge,
                                color = MaterialTheme.colorScheme.primary,
                                fontSize = 18.sp
                            )
                            Text(
                                text = "Y: ${currentY.toInt()} px",
                                style = MaterialTheme.typography.bodyLarge,
                                color = MaterialTheme.colorScheme.primary,
                                fontSize = 18.sp
                            )
                        }

                        Spacer(modifier = Modifier.height(12.dp))

                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            OutlinedButton(
                                modifier = Modifier.weight(1f),
                                onClick = {
                                    currentX = (screenWidthPx / 2).toFloat()
                                    currentY = (screenHeightPx / 2).toFloat()
                                }
                            ) {
                                Text("Center")
                            }
                            Button(
                                modifier = Modifier
                                    .weight(1.5f)
                                    .testTag("confirm_position_button"),
                                onClick = { onConfirm(currentX, currentY) }
                            ) {
                                Icon(Icons.Default.Check, contentDescription = null)
                                Spacer(modifier = Modifier.width(4.dp))
                                Text("Set Position")
                            }
                        }
                    }
                }
            }
        }
    }
}
