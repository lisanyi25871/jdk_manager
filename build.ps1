# ==========================================
# JDK 管理中心 - 一键全自动构建流水线 (CI/CD)
# ==========================================
Write-Host "🚀 开始执行一键打包流水线..." -ForegroundColor Cyan

# 1. 检查并生成图标
Write-Host "`n[1/4] 正在生成专属图标 logo.ico..." -ForegroundColor Yellow
python make_icon.py
if (-Not (Test-Path "logo.ico")) {
    Write-Host "❌ 图标生成失败，请检查 make_icon.py！" -ForegroundColor Red
    exit
}

# 2. 使用 PyInstaller 打包 Python 代码
Write-Host "`n[2/4] 正在将 Python 编译为独立 EXE (这步可能需要一两分钟)..." -ForegroundColor Yellow
pyinstaller -F -w -i logo.ico --add-data "logo.ico;." main.py
if (-Not (Test-Path "dist\main.exe")) {
    Write-Host "❌ PyInstaller 打包失败！" -ForegroundColor Red
    exit
}
# 重命名生成的 exe
Rename-Item -Path "dist\main.exe" -NewName "JDKManager.exe" -Force

# 3. 动态生成 Inno Setup 配置文件 (.iss)
Write-Host "`n[3/4] 正在生成 Inno Setup 安装包配置脚本..." -ForegroundColor Yellow
$currentPath = Get-Location
$issContent = @"
[Setup]
AppName=JDK 管理中心
AppVersion=1.0.0
AppPublisher=JDKManager Dev
DefaultDirName={autopf}\JDKManager
OutputBaseFilename=JDKManager_Installer_v1.0
OutputDir=$currentPath\Output
SetupIconFile=$currentPath\logo.ico
UninstallDisplayIcon={app}\JDKManager.exe
Compression=lzma
SolidCompression=yes
PrivilegesRequired=admin

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标"; Flags: unchecked

[Files]
Source: "$currentPath\dist\JDKManager.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\JDK 管理中心"; Filename: "{app}\JDKManager.exe"
Name: "{autodesktop}\JDK 管理中心"; Filename: "{app}\JDKManager.exe"; Tasks: desktopicon

[Registry]
; 卸载时强行清理开机自启注册表
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "JDKManagerDaemon"; Flags: uninsdeletevalue
"@

Set-Content -Path "installer_build.iss" -Value $issContent -Encoding UTF8

# 4. 调用 ISCC 命令行编译器生成最终安装包
Write-Host "`n[4/4] 正在调用 ISCC.exe 编译最终安装包..." -ForegroundColor Yellow
# 默认情况下 Inno Setup 6 会安装在这个路径
$isccPath = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

if (Test-Path $isccPath) {
    & $isccPath "installer_build.iss"
    Write-Host "`n🎉 全部构建完成！" -ForegroundColor Green
    Write-Host "您的终极安装包已生成在: $currentPath\Output\JDKManager_Installer_v1.0.exe" -ForegroundColor Green
} else {
    Write-Host "`n❌ 找不到 Inno Setup 编译器，请确认是否已安装 Inno Setup 6！" -ForegroundColor Red
    Write-Host "期望路径: $isccPath" -ForegroundColor Gray
}

# 5. 清理临时文件 (保持目录整洁)
Write-Host "`n🧹 正在清理构建过程中的临时文件..." -ForegroundColor DarkGray
Remove-Item -Path "installer_build.iss" -ErrorAction SilentlyContinue
Remove-Item -Path "main.spec" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force -Path "build" -ErrorAction SilentlyContinue