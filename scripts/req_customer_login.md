需求点：customer 应用服务【用户登录】逻辑质量分析

背景：商户/运营用户通过「登录号(loginNo) + 登录系统类型(loginSystemType)」调用 customer 应用服务的登录接口，由 LoginServiceImpl.checkPwd 完成核心校验。

实际校验链路（来自源码）：
1. 入参 loginType：1=用户名密码，2=微信，3=云闪付，4=手机号一键，5=验证码登录。
2. noCheckLoginPwd 判定：loginType 为 2/3（微信、云闪付）或 4（手机号一键）时为真，跳过密码校验。
3. loginType=5（验证码登录）时，入参 password 实为 String.valueOf(true)，表示短信/邮件验证码已校验通过。
4. 校验顺序：
   a. 按 loginNo + loginSystemType 查 LoginInfo；不存在 → 提示「用户名或密码错误」；状态非 NORMAL → 「账号未开启登录功能」。
   b. 按 LoginInfo.operatorId 查 Operator；为空 → 「用户名或密码错误」；状态非 NORMAL → 「不能使用登录功能」。
   c. 需校验密码时，查 UserInfo（operator.userId）；PwdUtil.loginPwdEncrypt(password, salt) 与库 loginPwd 比对；不一致 → 累加错误次数。
   d. 锁定策略：ErrorNum >= 4 时置 LOCKING，锁定 60 分钟（getLoginLockDuration=60）后自动解锁，提示「账号被锁定，请在 xxx 时间后重试」；未达阈值提示「密码错误，您还可以尝试 X 次」（4 - errorNum）。
   e. 用户状态：CLOSE→已封禁，PENDING_CANCEL→注销中，CANCEL→已注销，分别拦截。
5. 全部通过返回 LoginInfo，后续另行生成 token。

请分析该登录逻辑的实现质量与潜在风险，重点关注：
- 锁定时间边界（60 分钟解锁的精确性与并发安全）；
- 免密登录（微信/云闪付/手机号一键）是否会绕过关键校验；
- 错误次数 ErrorNum 的并发累加与回滚（登录成功是否清零）；
- 密码加密方式（loginPwdEncrypt）的强度与盐值管理；
- 提示信息是否存在用户名枚举风险（不存在/状态下均返回「用户名或密码错误」的差异化）。
