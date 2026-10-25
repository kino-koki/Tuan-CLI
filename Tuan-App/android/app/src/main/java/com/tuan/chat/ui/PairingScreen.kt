package com.tuan.chat.ui

import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tuan.chat.model.AgentInfo
import com.tuan.chat.model.HelloMessage
import com.tuan.chat.ws.DispatchClient.ConnectionState
import com.tuan.chat.ws.DispatchRepository
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

// Claude / Anthropic 设计系统色板
private val ClaudeCoral = Color(0xFFD97757)
private val ClaudeCoralLight = Color(0xFFE8927C)
private val ClaudeDark = Color(0xFF141413)
private val ClaudeCream = Color(0xFFFAF9F5)
private val ClaudeText = Color(0xFFECECE8)
private val ClaudeTextDim = Color(0xFF9A9A92)
private val ClaudeGreen = Color(0xFF788C5D)
private val ClaudeBlue = Color(0xFF6A9BCC)
private val ClaudeSuccess = Color(0xFF6FCF97)
private val ClaudeError = Color(0xFFEF4444)

/**
 * 配对屏: 输入桌面地址 + 6 位配对码.
 *
 * 设计: Anthropic Claude 珊瑚色体系 (warm, trustworthy, thoughtfully restrained)
 * 状态:
 * - DISCONNECTED/CONNECTING: 输入表单
 * - PAIRING: 显示 6 位配对码 + Q 弹动画 + 倒计时
 * - PAIRED: 由 MainActivity 切换到 DispatchScreen
 *
 * 动画设计 (Q 弹 / Anthropic 同款验证码体系):
 * - 每个数字卡片以 staggered spring 弹入 (cubic-bezier(.34,1.56,.64,1))
 * - 呼吸圆点持续脉冲 (无限循环)
 * - 状态切换时 bounceIn 过渡
 * - 倒计时圆环平滑变化
 */
@Composable
fun PairingScreen(viewModel: DispatchRepository) {
    val state by viewModel.client.state.collectAsState()
    val hello by viewModel.client.hello.collectAsState()
    val error by viewModel.client.lastError.collectAsState()

    var host by remember { mutableStateOf("192.168.1.5") }
    var port by remember { mutableStateOf("8788") }
    var code by remember { mutableStateOf("") }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Tuan-Chat") },
            )
        },
        containerColor = ClaudeDark,
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(28.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            // Logo
            Text(
                "Tuan-Chat",
                style = MaterialTheme.typography.headlineMedium.copy(fontWeight = FontWeight.Bold),
                color = ClaudeCoral,
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                "远程调度桌面 Agent",
                style = MaterialTheme.typography.bodySmall.copy(letterSpacing = 2.sp),
                color = ClaudeTextDim,
            )
            Spacer(modifier = Modifier.height(28.dp))

            // 状态卡片
            PairingCard(state, hello.value, error)

            Spacer(modifier = Modifier.height(28.dp))

            if (state != ConnectionState.PAIRING) {
                // 输入表单
                OutlinedTextField(
                    value = host,
                    onValueChange = { host = it },
                    label = { Text("桌面地址 (IP)") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                )
                Spacer(modifier = Modifier.height(12.dp))
                OutlinedTextField(
                    value = port,
                    onValueChange = { port = it.filter(Char::isDigit) },
                    label = { Text("端口") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                )
                Spacer(modifier = Modifier.height(12.dp))
                OutlinedTextField(
                    value = code,
                    onValueChange = { code = it.filter(Char::isDigit) },
                    label = { Text("配对码 (6 位)") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    maxLength = 6,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                )
                Spacer(modifier = Modifier.height(20.dp))

                Button(
                    onClick = { viewModel.pair(host, port.toIntOrNull() ?: 8788, code) },
                    enabled = host.isNotBlank() && code.length == 6,
                    modifier = Modifier.fillMaxWidth().height(50.dp),
                    shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = ClaudeCoral,
                        disabledContainerColor = ClaudeCoral.copy(alpha = 0.3f),
                    ),
                ) {
                    Text("连接", fontWeight = FontWeight.SemiBold)
                }
                Spacer(modifier = Modifier.height(14.dp))

                if (error != null) {
                    Text(error, color = ClaudeError, style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
}

/** 配对状态卡片: 呼吸圆点 / 配对码 / 成功 / 错误. */
@Composable
private fun PairingCard(state: ConnectionState, hello: HelloMessage?, error: String?) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(24.dp),
        color = Color(0x0FFF_FFFF),
        borderBrush = Brush.solidColor(Color(0x1AFF_FFFF)),
        borderThickness = 1.dp,
        shadowElevation = 0.dp,
    ) {
        Column(
            modifier = Modifier.padding(32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            when (state) {
                ConnectionState.PAIRING -> {
                    if (hello != null) PairingCodeDisplay(hello)
                    else {
                        PulsingIndicator()
                        Spacer(modifier = Modifier.height(16.dp))
                        Text("等待连接...", color = ClaudeTextDim)
                    }
                }
                ConnectionState.PAIRED -> SuccessState()
                ConnectionState.ERROR -> {
                    Text(error ?: "连接失败", color = ClaudeError, textAlign = TextAlign.Center)
                }
                else -> {
                    PulsingIndicator()
                    Spacer(modifier = Modifier.height(16.dp))
                    Text("等待手机连接...", color = ClaudeTextDim)
                }
            }
        }
    }
}

/** 配对码显示: 6 个数字卡片 + Q 弹 staggered 弹入 + 倒计时 + 代理列表. */
@Composable
private fun PairingCodeDisplay(hello: HelloMessage) {
    val pairCode = hello.pairCode
    val codeChars = pairCode.chunked(1)

    // 倒计时
    var countdown by remember { mutableIntStateOf(60) }
    LaunchedEffect(pairCode) {
        countdown = 60
        while (true) {
            delay(1000)
            countdown--
            if (countdown <= 0) break
        }
    }

    // 呼吸圆点
    PulsingIndicator()
    Spacer(modifier = Modifier.height(20.dp))

    // 标签
    Text(
        "请在手机上输入配对码",
        style = MaterialTheme.typography.bodySmall.copy(letterSpacing = 1.sp),
        color = ClaudeTextDim,
    )
    Spacer(modifier = Modifier.height(16.dp))

    // 数字卡片: staggered spring 弹入
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        codeChars.forEachIndexed { index, char ->
            DigitCard(digit = char, index = index)
        }
    }
    Spacer(modifier = Modifier.height(24.dp))

    // 倒计时
    CountdownTimer(remaining = countdown, total = 60)
    Spacer(modifier = Modifier.height(24.dp))

    // 可用代理列表
    AgentList(hello.agents)
}

/**
 * 单个数字卡片: spring 弹入动画.
 * 每个数字延迟 index * 80ms 开始弹入, 使用 bounce spring 曲线.
 * Claude 珊瑚色体系.
 */
@Composable
private fun DigitCard(digit: String, index: Int) {
    val shape = RoundedCornerShape(14.dp)

    // 使用 Animatable 精确控制 stagger + spring
    val scaleAnim = remember { Animatable(0.3f) }
    val alphaAnim = remember { Animatable(0f) }

    LaunchedEffect(Unit) {
        delay(index * 80L) // stagger 延迟
        val bounceSpring = spring(
            dampingRatio = Spring.DampingRatioMediumBouncy,
            stiffness = Spring.StiffnessMediumLow,
        )
        launch { scaleAnim.animateTo(1f, bounceSpring) }
        launch { alphaAnim.animateTo(1f, tween(400, easing = FastOutSlowInEasing)) }
    }

    Box(
        modifier = Modifier
            .graphicsLayer(
                scaleX = scaleAnim.value,
                scaleY = scaleAnim.value,
                alpha = alphaAnim.value,
            )
            .width(46.dp)
            .height(60.dp)
            .clip(shape)
            .background(
                Brush.linearGradient(
                    colors = listOf(
                        ClaudeCoral.copy(alpha = 0.25f),
                        ClaudeCoral.copy(alpha = 0.1f),
                    ),
                ),
            )
            .border(1.dp, ClaudeCoral.copy(alpha = 0.3f), shape),
        contentAlignment = Alignment.Center,
    ) {
        Text(digit, fontSize = 26.sp, fontWeight = FontWeight.Bold, color = ClaudeCoralLight)
    }
}

/** 倒计时圆环. */
@Composable
private fun CountdownTimer(remaining: Int, total: Int) {
    val progress by animateFloatAsState(
        targetValue = remaining.toFloat() / total,
        animationSpec = tween(1000),
        label = "countdown",
    )
    val isWarning = remaining <= 10

    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Box(modifier = Modifier.size(36.dp), contentAlignment = Alignment.Center) {
            CircularProgressIndicator(
                progress = { progress },
                modifier = Modifier.fillMaxSize().rotate(-90f),
                strokeWidth = 3.dp,
                color = if (isWarning) ClaudeError else ClaudeCoral,
                trackColor = Color(0x1AFF_FFFF),
            )
        }
        Text(
            "${remaining}s",
            fontSize = 14.sp,
            color = ClaudeTextDim,
            fontWeight = if (isWarning) FontWeight.Bold else FontWeight.Normal,
        )
    }
}

/** 可用代理列表. */
@Composable
private fun AgentList(agents: List<AgentInfo>) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Text(
            "可用代理",
            fontSize = 11.sp,
            letterSpacing = 1.5.sp,
            color = ClaudeTextDim.copy(alpha = 0.7f),
            fontWeight = FontWeight.Medium,
        )
        Spacer(modifier = Modifier.height(8.dp))
        agents.forEach { agent ->
            Row(
                modifier = Modifier.padding(vertical = 3.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Box(
                    modifier = Modifier
                        .size(7.dp)
                        .clip(CircleShape)
                        .background(
                            if (agent.healthy) ClaudeSuccess
                            else ClaudeTextDim.copy(alpha = 0.4f),
                        ),
                )
                Text(
                    agent.name + (agent.version?.let { " v$it" } ?: ""),
                    fontSize = 13.sp,
                    color = ClaudeText,
                )
            }
        }
    }
}

/** 呼吸脉冲指示器: 无限循环的脉冲圆环. Claude 珊瑚色. */
@Composable
private fun PulsingIndicator() {
    val pulseAnim by rememberInfiniteTransition(label = "p1").animateFloat(
        initialValue = 1f,
        targetValue = 2.0f,
        animationSpec = infiniteRepeatable(
            animation = tween(2000, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "p1",
    )
    val pulseAlpha by rememberInfiniteTransition(label = "p2").animateFloat(
        initialValue = 0.6f,
        targetValue = 0f,
        animationSpec = infiniteRepeatable(
            animation = tween(2000, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "p2",
    )

    Box(modifier = Modifier.size(56.dp), contentAlignment = Alignment.Center) {
        Box(
            modifier = Modifier
                .size(56.dp)
                .graphicsLayer(scaleX = pulseAnim, scaleY = pulseAnim, alpha = pulseAlpha)
                .clip(CircleShape)
                .border(2.dp, ClaudeCoral, CircleShape),
        )
        Box(
            modifier = Modifier
                .size(12.dp)
                .clip(CircleShape)
                .background(ClaudeCoral),
        )
    }
}

/** 配对成功状态: bounceIn 弹入. */
@Composable
private fun SuccessState() {
    val scaleAnim = remember { Animatable(0.5f) }

    LaunchedEffect(Unit) {
        scaleAnim.animateTo(1f, spring(
            dampingRatio = Spring.DampingRatioLowBouncy,
            stiffness = Spring.StiffnessLow,
        ))
    }

    Column(
        modifier = Modifier.graphicsLayer(scaleX = scaleAnim.value, scaleY = scaleAnim.value),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            modifier = Modifier
                .size(56.dp)
                .clip(CircleShape)
                .background(Brush.linearGradient(listOf(ClaudeSuccess, ClaudeGreen))),
            contentAlignment = Alignment.Center,
        ) {
            Text("\u2713", fontSize = 28.sp, color = Color.White, fontWeight = FontWeight.Bold)
        }
        Spacer(modifier = Modifier.height(16.dp))
        Text("配对成功", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = ClaudeSuccess)
    }
}
