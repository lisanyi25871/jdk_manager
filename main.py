import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, scrolledtext
import subprocess
import threading
import queue
import os
import re
import json
import sys
import ctypes
import urllib.request
import time
import winreg
from PIL import Image, ImageDraw
import pystray

# 隐藏初始控制台黑框
if sys.platform == 'win32':
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd: ctypes.windll.user32.ShowWindow(hwnd, 0)

CREATE_NO_WINDOW = 0x08000000

class JDKManagerApp:
    def resource_path(self, relative_path):
        """核心黑科技：获取资源的绝对路径，完美兼容 PyInstaller 单文件打包机制"""
        try:
            # PyInstaller 运行时，会把真实路径存在 sys._MEIPASS 中
            base_path = sys._MEIPASS
        except Exception:
            # 在普通的 Python 环境下运行
            base_path = os.path.abspath(".")
        return os.path.join(base_path, relative_path)
    def __init__(self, root):
        self.root = root
        self.root.title("全能 JDK 管理中心 - 终极缓存常驻版")
        self.root.geometry("850x600")
        
        self.log_queue = queue.Queue()
        self.is_processing = False
        self.dynamic_catalog = {} 
        
        # ==========================================
        # 核心权限修复：使用 Windows 标准 APPDATA 目录
        # 存放到 C:\Users\你的用户名\AppData\Roaming\JDKManager\
        # 彻底免疫管理员提权导致的路径偏移和 C 盘只读限制
        # ==========================================
        appdata_dir = os.environ.get("APPDATA", os.path.expanduser("~"))
        self.cache_dir = os.path.join(appdata_dir, "JDKManager")
        os.makedirs(self.cache_dir, exist_ok=True) 
        self.cache_file = os.path.join(self.cache_dir, "list.json")
        
        self.tray_icon = None
        
        self.setup_ui()
        self.check_queue() 
        
        # 拦截右上角关闭，改为隐藏到托盘
        self.root.protocol('WM_DELETE_WINDOW', self.hide_window)
        
        self.setup_autostart()
        self.create_tray_icon()
        
        # 线程 1：启动时立刻执行瞬发扫描（读取本地缓存）
        threading.Thread(target=self.fast_boot_and_scan, daemon=True).start()
        # 独立常驻线程：每日静默检查
        threading.Thread(target=self.daily_check_loop, daemon=True).start()

    # ==========================================
    # 系统托盘与开机自启逻辑
    # ==========================================
    def create_tray_icon(self):
        try:
            # 直接调用智能寻址，加载现成的高清 logo.ico
            icon_path = self.resource_path("logo.ico")
            image = Image.open(icon_path)
        except Exception as e:
            self.write_log(f"⚠️ 无法加载外部托盘图标: {e}")
            # 极限兜底：万一图标丢了，临时画个黑块防崩溃
            image = Image.new('RGB', (64, 64), color=(30, 30, 30))
            draw = ImageDraw.Draw(image)
            draw.text((12, 20), "JDK", fill=(0, 255, 0))

        menu = pystray.Menu(
            pystray.MenuItem("显示主面板", self.show_window),
            pystray.MenuItem("强制同步仓库", lambda: threading.Thread(target=self.thread2_sync_and_revalidate, daemon=True).start()),
            pystray.MenuItem("完全退出", self.quit_app)
        )
        self.tray_icon = pystray.Icon("JDKManager", image, "JDK 常驻管理中心", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def hide_window(self):
        self.root.withdraw()
        if self.tray_icon:
            self.tray_icon.notify("已最小化到系统托盘，将在后台为您每天监测 JDK 更新。", title="JDK 管理中心")

    def show_window(self, icon=None, item=None):
        self.root.after(0, self.root.deiconify)

    def quit_app(self, icon=None, item=None):
        if self.tray_icon: self.tray_icon.stop()
        self.root.quit()
        sys.exit()

    def setup_autostart(self):
        try:
            exe_path = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__)
            if not getattr(sys, 'frozen', False):
                exe_path = f'"{sys.executable.replace("python.exe", "pythonw.exe")}" "{exe_path}"'
            else:
                exe_path = f'"{exe_path}"'
                
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run', 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, 'JDKManagerDaemon', 0, winreg.REG_SZ, exe_path)
            winreg.CloseKey(key)
        except Exception as e:
            self.write_log(f"⚠️ 开启自动启动失败: {e}")

    def daily_check_loop(self):
        """每日后台轻量化 API 查岗，绝不执行耗时的 scoop update"""
        time.sleep(300) 
        while True:
            self.write_log("\n[后台监测] 正在执行每日例行静默检查...")
            has_update, msg = self.silent_api_check()
            if has_update and self.tray_icon:
                self.tray_icon.notify(msg, title="🔔 发现新的 JDK 更新！")
            time.sleep(86400)

    def silent_api_check(self):
        list_res = subprocess.run("powershell -Command scoop list", capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
        installed = {parts[0]: parts[1] for line in list_res.stdout.splitlines() if len(parts := line.split()) >= 2 and ('jdk' in parts[0].lower() or 'liberica' in parts[0].lower())}
        if not installed: return False, ""

        mirror_base_url = "https://ghproxy.net/https://raw.githubusercontent.com/ScoopInstaller/Java/master/bucket/"
        updates = []
        for pkg, local_ver in installed.items():
            try:
                req = urllib.request.Request(f"{mirror_base_url}{pkg}.json", headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=8) as response:
                    latest_ver = json.loads(response.read().decode('utf-8')).get("version")
                    if latest_ver and latest_ver != local_ver:
                        updates.append(f"{pkg}: {local_ver} -> {latest_ver}")
            except: pass

        if updates: return True, "以下环境有新版本：\n" + "\n".join(updates) + "\n点击托盘打开面板进行升级。"
        return False, ""

    # ==========================================
    # UI 布局
    # ==========================================
    def setup_ui(self):
        style = ttk.Style()
        style.configure("TButton", font=("Microsoft YaHei", 9))
        
        frame_top = ttk.LabelFrame(self.root, text=" 💻 本地已安装 JDK (后台自动监测) ", padding=10)
        frame_top.pack(fill=tk.BOTH, padx=15, pady=5)
        
        columns = ("pkg", "version", "status")
        self.tree = ttk.Treeview(frame_top, columns=columns, show="headings", height=5)
        self.tree.heading("pkg", text="实际包名")
        self.tree.heading("version", text="当前版本")
        self.tree.heading("status", text="更新状态")
        self.tree.column("pkg", width=220)
        self.tree.column("version", width=120)
        self.tree.column("status", width=220)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        frame_top_btn = tk.Frame(frame_top)
        frame_top_btn.pack(side=tk.RIGHT, fill=tk.Y, padx=10)
        
        ttk.Button(frame_top_btn, text="🌐 配置加速代理", command=self.configure_proxy).pack(fill=tk.X, pady=2)
        ttk.Button(frame_top_btn, text="🔄 强制同步仓库", command=lambda: threading.Thread(target=self.thread2_sync_and_revalidate, daemon=True).start()).pack(fill=tk.X, pady=2)
        ttk.Button(frame_top_btn, text="⬆️ 升级选中版本", command=self.update_selected).pack(fill=tk.X, pady=2)
        ttk.Button(frame_top_btn, text="🗑️ 卸载选中版本", command=self.uninstall_selected).pack(fill=tk.X, pady=2)

        frame_mid = ttk.LabelFrame(self.root, text=" ☁️ 可下载 LTS 库与全局设置 ", padding=10)
        frame_mid.pack(fill=tk.X, padx=15, pady=5)
        
        tk.Label(frame_mid, text="1. 软件厂商:").grid(row=0, column=0, padx=5, pady=5)
        self.cmb_vendor = ttk.Combobox(frame_mid, values=["正在极速加载..."], state="readonly", width=33)
        self.cmb_vendor.current(0)
        self.cmb_vendor.grid(row=0, column=1, padx=5, pady=5)
        self.cmb_vendor.bind("<<ComboboxSelected>>", self.on_vendor_change)
        
        tk.Label(frame_mid, text="2. LTS 版本:").grid(row=0, column=2, padx=5, pady=5)
        self.cmb_version = ttk.Combobox(frame_mid, state="readonly", width=12)
        self.cmb_version.grid(row=0, column=3, padx=5, pady=5)
        
        frame_mid_btns = tk.Frame(frame_mid)
        frame_mid_btns.grid(row=0, column=4, padx=10)
        ttk.Button(frame_mid_btns, text="⬇️ 下载选中版本", command=self.install_single).pack(side=tk.LEFT, padx=5)
        ttk.Button(frame_mid_btns, text="🚀 一键拉满厂商", command=self.install_all_lts).pack(side=tk.LEFT, padx=5)
        
        ttk.Separator(frame_mid, orient=tk.HORIZONTAL).grid(row=1, column=0, columnspan=5, sticky="ew", pady=10)
        ttk.Button(frame_mid, text="⚙️ 设为系统全局默认 (配置 JAVA_HOME，修复所有软件识别)", command=self.set_global_java_home).grid(row=2, column=0, columnspan=5)

        frame_log = ttk.LabelFrame(self.root, text=" 📈 实时终端与进度输出 ", padding=10)
        frame_log.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)
        
        self.log_area = scrolledtext.ScrolledText(frame_log, bg="#000000", fg="#00ff00", font=("Consolas", 9))
        self.log_area.pack(fill=tk.BOTH, expand=True)

    def check_queue(self):
        while not self.log_queue.empty():
            self.log_area.insert(tk.END, self.log_queue.get())
            self.log_area.see(tk.END)
        self.root.after(50, self.check_queue) 

    def write_log(self, msg, newline=True):
        if newline: self.log_queue.put(msg + "\n")
        else: self.log_queue.put(msg)

    def on_vendor_change(self, event):
        vendor = self.cmb_vendor.get()
        if vendor in self.dynamic_catalog:
            versions = sorted(list(self.dynamic_catalog[vendor].keys()), key=lambda x: int(x.split()[1]))
            self.cmb_version.config(values=versions)
            if versions:
                default_ver = "LTS 17" if "LTS 17" in versions else versions[-1]
                self.cmb_version.set(default_ver)

    # ==========================================
    # 核心架构 1：瞬发扫描 (完美找回的极速缓存逻辑)
    # ==========================================
    def fast_boot_and_scan(self):
        """线程 1：仅读取文件名，极速填充 UI，不执行耗时网络拉取"""
        self.write_log("[极速启动] 正在纯本地读取缓存，全程 0 卡顿...")
        
        list_res = subprocess.run("powershell -Command scoop list", capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
        if list_res.returncode != 0:
            install_cmd = "Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser; Invoke-RestMethod -Uri https://get.scoop.sh | Invoke-Expression"
            self.run_cmd_stream(install_cmd, "自动部署 Scoop", on_success=self.fast_boot_and_scan)
            return
            
        bucket_check = subprocess.run("powershell -Command scoop bucket list", capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
        if "java" not in bucket_check.stdout: subprocess.run("powershell -Command scoop bucket add java", creationflags=CREATE_NO_WINDOW)
            
        aria2_check = subprocess.run("powershell -Command scoop list", capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
        if "aria2" not in aria2_check.stdout: subprocess.run("powershell -Command scoop install aria2", creationflags=CREATE_NO_WINDOW)
        subprocess.run("powershell -Command scoop config aria2-enabled true", creationflags=CREATE_NO_WINDOW)

        # 极速优化：只读文件名，不解析 JSON 内容！
        self.fast_build_download_catalog()
        
        # 极速优化：先拿 list.json 里的缓存垫底显示
        cached_versions = {}
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    cached_versions = json.load(f)
            except: pass
            
        self.fast_populate_installed_table(list_res.stdout, cached_versions)
        
        # UI 放行后，暗中唤醒线程 2 去干脏活累活
        threading.Thread(target=self.thread2_sync_and_revalidate, daemon=True).start()

    def fast_build_download_catalog(self):
        bucket_path = os.path.join(os.environ.get("USERPROFILE", ""), "scoop", "buckets", "java", "bucket")
        temp_catalog = { "BellSoft Liberica (完整版/游戏专用)": {}, "Adoptium Temurin (原 Eclipse)": {}, "Microsoft OpenJDK": {}, "Amazon Corretto": {} }

        if os.path.exists(bucket_path):
            for file in os.listdir(bucket_path):
                if not file.endswith(".json"): continue
                pkg = file[:-5] # 核心：只读取文件名！
                pkg_lower = pkg.lower()

                match = re.search(r'(?<!\d)(8|11|17|21|25)(?!\d)', pkg_lower)
                if not match: continue
                lts = f"LTS {match.group(1)}"

                if 'liberica' in pkg_lower and 'full' in pkg_lower and 'jre' not in pkg_lower:
                    if lts not in temp_catalog["BellSoft Liberica (完整版/游戏专用)"] or len(pkg) < len(temp_catalog["BellSoft Liberica (完整版/游戏专用)"][lts]):
                        temp_catalog["BellSoft Liberica (完整版/游戏专用)"][lts] = pkg
                elif 'temurin' in pkg_lower and 'jre' not in pkg_lower:
                    temp_catalog["Adoptium Temurin (原 Eclipse)"][lts] = pkg
                elif 'microsoft' in pkg_lower:
                    temp_catalog["Microsoft OpenJDK"][lts] = pkg
                elif 'corretto' in pkg_lower and 'jre' not in pkg_lower:
                    temp_catalog["Amazon Corretto"][lts] = pkg

        self.dynamic_catalog = {k: v for k, v in temp_catalog.items() if v}
        vendors = list(self.dynamic_catalog.keys())
        if vendors:
            self.root.after(0, lambda: self.cmb_vendor.config(values=vendors))
            self.root.after(0, lambda: self.cmb_vendor.current(0))
            self.root.after(0, lambda: self.on_vendor_change(None))

    def fast_populate_installed_table(self, list_output, cached_versions):
        installed = [(parts[0], parts[1]) for line in list_output.splitlines() if len(parts := line.split()) >= 2 and any(kw in parts[0].lower() for kw in ['jdk', 'java', 'liberica', 'temurin', 'corretto'])]
        self.root.after(0, lambda: self.tree.delete(*self.tree.get_children()))
        for pkg, ver in installed: 
            # 优化：如果命中缓存，立刻显示状态
            status = "⏳ 等待最新数据..."
            if pkg in cached_versions:
                status = f"[缓存] 可更新 ({cached_versions[pkg]})" if ver != cached_versions[pkg] else "[缓存] 已是最新"
            self.root.after(0, lambda p=pkg, v=ver, s=status: self.tree.insert("", tk.END, values=(p, v, s)))

    # ==========================================
    # 核心架构 2：后台幽灵同步 (原子更新 list.json)
    # ==========================================
    def thread2_sync_and_revalidate(self):
        """线程 2：处理联网拉取、提取版本号、原子级更新 list.json"""
        if self.is_processing: return
        self.is_processing = True

        self.write_log("\n[数据同步] 正在增量拉取官方最新仓库...")
        process = subprocess.Popen(["powershell", "-NoProfile", "-Command", "scoop update"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='ignore', creationflags=CREATE_NO_WINDOW, bufsize=1)
        for line in process.stdout: self.write_log(line.rstrip())
        process.wait()

        self.write_log("[数据同步] 开始解析最新版本号，并更新本地 list.json...")
        bucket_path = os.path.join(os.environ.get("USERPROFILE", ""), "scoop", "buckets", "java", "bucket")
        new_versions = {}
        
        if os.path.exists(bucket_path):
            for file in os.listdir(bucket_path):
                if file.endswith(".json"):
                    pkg_name = file[:-5]
                    try:
                        with open(os.path.join(bucket_path, file), "r", encoding="utf-8") as f:
                            new_versions[pkg_name] = json.load(f).get("version", "未知")
                    except: pass
        
        # 写入带有加强日志的 APPDATA 路径
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(new_versions, f, ensure_ascii=False, indent=2)
            self.write_log(f"[数据同步] ✅ 缓存更新完毕，文件保存在:\n{self.cache_file}")
        except Exception as e:
            self.write_log(f"[数据同步] ❌ 缓存写入失败: {e}")
            
        self.root.after(0, lambda: self.compare_and_update_ui(new_versions))
        self.is_processing = False

    def compare_and_update_ui(self, versions_dict):
        for item in self.tree.get_children():
            pkg = self.tree.item(item, "values")[0]
            current_ver = self.tree.item(item, "values")[1]
            latest_ver = versions_dict.get(pkg, "")
            if latest_ver:
                msg = f"🔥 可更新 ({latest_ver})" if current_ver != latest_ver else "✔️ 已是最新"
                self.tree.set(item, column="status", value=msg)

    # ==========================================
    # 下载执行器及底层操作
    # ==========================================
    def run_cmd_stream(self, cmd, task_name, on_success=None):
        self.write_log(f"\n[{task_name}] >>> 开始执行...")
        full_cmd = f"[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; {cmd}"
        process = subprocess.Popen(["powershell", "-NoProfile", "-Command", full_cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='ignore', creationflags=CREATE_NO_WINDOW, bufsize=1)
        
        buffer = ""
        error_detected = False
        while True:
            char = process.stdout.read(1)
            if not char: break
            if char == '\n':
                if buffer.strip():
                    self.write_log(buffer)
                    if "意外的 EOF" in buffer or "not valid" in buffer or "schannel: failed" in buffer: error_detected = True
                buffer = ""
            elif char == '\r':
                if buffer.strip(): self.write_log(buffer)
                buffer = ""
            else: buffer += char
                
        process.wait()
        if process.returncode == 0 and not error_detected:
            self.write_log(f"[{task_name}] ✅ 执行成功！")
            if on_success: on_success()
        else: self.write_log(f"[{task_name}] ❌ 发生错误，建议配置底层加速代理。")

    def configure_proxy(self):
        port = simpledialog.askstring("配置加速代理", "请输入代理端口号（如 Clash 为 7890）：\n【留空并确定则关闭代理】")
        if port is not None:
            if port.strip():
                cmd = f"scoop config proxy 127.0.0.1:{port}; git config --global http.proxy http://127.0.0.1:{port}; git config --global https.proxy http://127.0.0.1:{port}; git config --global http.sslBackend openssl; git config --global http.sslVerify false"
                self.run_cmd_stream(cmd, f"开启全局代理与 SSL 优化 (端口 {port})")
            else:
                cmd = "scoop config rm proxy; git config --global --unset http.proxy; git config --global --unset https.proxy; git config --global http.sslBackend schannel; git config --global http.sslVerify true"
                self.run_cmd_stream(cmd, "清理全局代理")

    def get_selected(self):
        if not (selected := self.tree.selection()): messagebox.showwarning("提示", "请先选中表格中的项！"); return None
        return self.tree.item(selected[0], "values")[0]

    def update_selected(self):
        if pkg := self.get_selected():
            if self.is_processing: return
            self.is_processing = True
            threading.Thread(target=lambda: self.run_cmd_stream(f"scoop update; scoop update {pkg}", f"更新 {pkg}", lambda: (setattr(self, 'is_processing', False), self.fast_boot_and_scan())), daemon=True).start()

    def uninstall_selected(self):
        if (pkg := self.get_selected()) and messagebox.askyesno("确认", f"确定卸载 {pkg} 吗？"):
            if self.is_processing: return
            self.is_processing = True
            threading.Thread(target=lambda: self.run_cmd_stream(f"scoop uninstall {pkg}", f"卸载 {pkg}", lambda: (setattr(self, 'is_processing', False), self.fast_boot_and_scan())), daemon=True).start()

    def install_single(self):
        vendor, lts = self.cmb_vendor.get(), self.cmb_version.get()
        if vendor not in self.dynamic_catalog or lts not in self.dynamic_catalog[vendor]: return
        if self.is_processing: return
        self.is_processing = True
        pkg = self.dynamic_catalog[vendor][lts]
        threading.Thread(target=lambda: self.run_cmd_stream(f"scoop update; scoop install java/{pkg}", f"下载 {pkg}", lambda: (setattr(self, 'is_processing', False), self.fast_boot_and_scan())), daemon=True).start()

    def install_all_lts(self):
        if (vendor := self.cmb_vendor.get()) not in self.dynamic_catalog: return
        pkgs = list(self.dynamic_catalog[vendor].values())
        if not messagebox.askyesno("一键拉满", f"即将串行下载 {vendor} 所有 LTS 版本，确认？"): return
        if self.is_processing: return
        self.is_processing = True
        def task():
            subprocess.run("powershell -Command scoop update", creationflags=CREATE_NO_WINDOW)
            for pkg in pkgs: self.run_cmd_stream(f"scoop install java/{pkg}", f"队列下载: {pkg}")
            self.is_processing = False
            self.fast_boot_and_scan()
        threading.Thread(target=task, daemon=True).start()

    def set_global_java_home(self):
        if not (pkg := self.get_selected()): return
        java_home_path = os.path.join(os.environ.get("USERPROFILE"), "scoop", "apps", pkg, "current")
        if not messagebox.askyesno("设置全局环境", f"将系统的 JAVA_HOME 指向：\n{pkg}\n\n这会让电脑上所有软件默认使用此版本，确认吗？"): return
        cmd = f'setx JAVA_HOME "{java_home_path}"'
        if self.is_processing: return
        self.is_processing = True
        threading.Thread(target=lambda: self.run_cmd_stream(cmd, f"设置全局 JAVA_HOME", lambda: (setattr(self, 'is_processing', False), messagebox.showinfo("成功", "JAVA_HOME 环境变量已更新！\n请重启需要用到 Java 的应用（如各类游戏启动器）。"))), daemon=True).start()

if __name__ == "__main__":
    root = tk.Tk()
    app = JDKManagerApp(root)
    root.mainloop()