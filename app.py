import tkinter as tk
from tkinter import messagebox, filedialog, Toplevel, ttk, simpledialog
import cv2
import threading
import time
import configparser
import os
import sys
from pathlib import Path
from PIL import Image, ImageTk, ImageDraw, ImageFont
import ipaddress
from queue import Queue
import winsound  # Только для Windows

# Константы
MOTION_DEFAULT_SENSITIVITY = 500
CONFIG_SECTION = 'Camera'
CONFIG_KEY_CONNECTION_MODE = 'connection_mode'
CONFIG_KEY_URL = 'url'
CONFIG_KEY_IP = 'ip'
CONFIG_KEY_PORT = 'port'
CONFIG_KEY_USERNAME = 'username'
CONFIG_KEY_PASSWORD = 'password'
CONFIG_KEY_MOTION_SENSITIVITY = 'motion_sensitivity'
CONFIG_KEY_STREAM_PATH = 'stream_path'
CONFIG_KEY_IGNORE_MASK = 'ignore_mask'  # Зоны игнорирования
CONFIG_KEY_DETECTION_MASK = 'detection_mask'  # Зоны детекции
CONFIG_KEY_SOUND_FILE = 'sound_file'  # Звуковой файл
SECRET_CONFIG_SECTION = 'SecretPaths'
SECRET_CONFIG_KEY_PATH = 'secret_path'
HIDE_LOG_KEY = 'hide_log'
APP_VERSION = "v0.2"
AUTHOR = "Разин Г.В."


class CameraApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Nexora")
        self.root.geometry("800x650")
        self.root.resizable(True, True)

        # Определяем директорию приложения
        if getattr(sys, 'frozen', False):
            self.app_dir = os.path.dirname(sys.executable)
        else:
            self.app_dir = os.path.dirname(os.path.abspath(__file__))

        # Установка иконки, если файл существует
        icon_path = os.path.join(self.app_dir, "app.ico")
        if os.path.exists(icon_path):
            try:
                self.root.iconbitmap(icon_path)
            except Exception as e:
                print(f"Предупреждение: не удалось загрузить иконку: {e}")

        self.main_settings_path = os.path.join(self.app_dir, "settings.ini")
        self.secret_settings_path = None
        self.hide_log = False  # По умолчанию журнал отображается

        # --- Новые атрибуты для профилей ---
        self.profiles = {}
        self.current_profile_name = "Default"
        # ------------------------------------

        # --- Атрибуты камеры (из профиля) ---
        self.connection_mode = 'url'
        self.camera_url = '0'
        self.ip = '192.168.1.64'
        self.port = '554'
        self.username = 'admin'
        self.password = ''
        self.stream_path = '/stream1'
        self.motion_sensitivity = MOTION_DEFAULT_SENSITIVITY
        self.ignore_mask_rects = []  # [(x1, y1, x2, y2), ...] — в координатах оригинального кадра
        self.detection_mask_rects = []  # [(x1, y1, x2, y2), ...] — в координатах оригинального кадра
        self.sound_file = ""
        # ------------------------------------

        self.alert_window = None
        self.is_running = False
        self.cap = None
        self.last_frame = None
        self.message_queue = Queue()

        # Загружаем основные настройки и профили
        self.load_main_settings()
        self.load_profiles()

        # UI инициализируется ПОСЛЕ загрузки профилей, но ДО применения
        self.setup_ui()

        # Применяем профиль ПОСЛЕ инициализации UI
        self.apply_profile(self.current_profile_name)

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.after(100, self.process_messages)

    def load_main_settings(self):
        config = configparser.ConfigParser()
        if os.path.exists(self.main_settings_path):
            config.read(self.main_settings_path, encoding='utf-8')
            if SECRET_CONFIG_SECTION in config:
                self.secret_settings_path = config[SECRET_CONFIG_SECTION].get(SECRET_CONFIG_KEY_PATH, '')
                self.current_profile_name = config[SECRET_CONFIG_SECTION].get('current_profile', 'Default')
                self.hide_log = config[SECRET_CONFIG_SECTION].getboolean(HIDE_LOG_KEY, fallback=False)

        if not self.secret_settings_path or not os.path.exists(self.secret_settings_path):
            self.open_settings_file_dialog()
            if not self.secret_settings_path:
                default_secret = os.path.expanduser("~/nexora_secret_settings.ini")
                self.secret_settings_path = default_secret
                self.save_main_settings()

    def save_main_settings(self):
        config = configparser.ConfigParser()
        config[SECRET_CONFIG_SECTION] = {
            SECRET_CONFIG_KEY_PATH: self.secret_settings_path,
            'current_profile': self.current_profile_name,
            HIDE_LOG_KEY: str(self.hide_log)
        }
        try:
            with open(self.main_settings_path, 'w', encoding='utf-8') as f:
                config.write(f)
        except Exception as e:
            self.message_queue.put(("error", f"Не удалось сохранить основной файл настроек:\n{e}"))

    def open_settings_file_dialog(self):
        """Открывает диалог для выбора файла настроек и настройки отображения журнала."""
        dialog = Toplevel(self.root)
        dialog.title("Настройки")
        dialog.geometry("500x250")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="Настройки приложения", font=("Arial", 10, "bold")).pack(pady=(10, 5))

        current_path_label = tk.Label(dialog, text=f"Файл профилей: {self.secret_settings_path or 'Не задан'}",
                                      fg="blue", wraplength=450)
        current_path_label.pack(pady=(0, 10))

        def browse_file():
            file_path = filedialog.asksaveasfilename(
                title="Сохранить файл настроек",
                defaultextension=".ini",
                filetypes=[("INI files", "*.ini"), ("All files", "*.*")]
            )
            if file_path:
                self.secret_settings_path = file_path
                current_path_label.config(text=f"Файл профилей: {self.secret_settings_path}")
                self.message_queue.put(("log", f"Выбран файл настроек: {self.secret_settings_path}"))

        tk.Button(dialog, text="Обзор...", command=browse_file).pack(pady=5)

        hide_log_var = tk.BooleanVar(value=self.hide_log)
        tk.Checkbutton(dialog, text="Скрыть журнал событий в главном окне", variable=hide_log_var).pack(pady=10)

        def confirm_and_close():
            self.hide_log = hide_log_var.get()
            if not self.secret_settings_path:
                self.secret_settings_path = os.path.expanduser("~/nexora_secret_settings.ini")
            self.save_main_settings()
            self.update_log_visibility()
            dialog.destroy()

        tk.Button(dialog, text="OK", command=confirm_and_close).pack(pady=10)
        dialog.wait_window()

    def update_log_visibility(self):
        """Скрывает или показывает панель журнала в зависимости от настройки."""
        if hasattr(self, 'log_frame'):
            if self.hide_log:
                self.log_frame.pack_forget()
            else:
                self.log_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 5))

    def load_profiles(self):
        """Загружает профили из секретного файла."""
        config = configparser.ConfigParser()
        if os.path.exists(self.secret_settings_path):
            config.read(self.secret_settings_path, encoding='utf-8')
            for section_name in config.sections():
                if section_name.startswith('Profile_'):
                    profile_name = section_name[8:]
                    self.profiles[profile_name] = {
                        'connection_mode': config[section_name].get(CONFIG_KEY_CONNECTION_MODE, 'url'),
                        'camera_url': config[section_name].get(CONFIG_KEY_URL, '0'),
                        'ip': config[section_name].get(CONFIG_KEY_IP, '192.168.1.64'),
                        'port': config[section_name].get(CONFIG_KEY_PORT, '554'),
                        'username': config[section_name].get(CONFIG_KEY_USERNAME, 'admin'),
                        'password': config[section_name].get(CONFIG_KEY_PASSWORD, ''),
                        'stream_path': config[section_name].get(CONFIG_KEY_STREAM_PATH, '/stream1'),
                        'motion_sensitivity': config[section_name].getint(
                            CONFIG_KEY_MOTION_SENSITIVITY, MOTION_DEFAULT_SENSITIVITY
                        ),
                        'sound_file': config[section_name].get(CONFIG_KEY_SOUND_FILE, ''),
                        'ignore_mask': self._parse_mask(config[section_name].get(CONFIG_KEY_IGNORE_MASK, '')),
                        'detection_mask': self._parse_mask(config[section_name].get(CONFIG_KEY_DETECTION_MASK, ''))
                    }

    def save_profiles(self):
        """Сохраняет все профили в секретный файл."""
        config = configparser.ConfigParser()
        if os.path.exists(self.secret_settings_path):
            config.read(self.secret_settings_path, encoding='utf-8')

        for profile_name, settings in self.profiles.items():
            section_name = f'Profile_{profile_name}'
            config[section_name] = {
                CONFIG_KEY_CONNECTION_MODE: settings['connection_mode'],
                CONFIG_KEY_URL: str(settings['camera_url']),
                CONFIG_KEY_IP: str(settings['ip']),
                CONFIG_KEY_PORT: str(settings['port']),
                CONFIG_KEY_USERNAME: str(settings['username']),
                CONFIG_KEY_PASSWORD: str(settings['password']),
                CONFIG_KEY_STREAM_PATH: str(settings['stream_path']),
                CONFIG_KEY_MOTION_SENSITIVITY: str(settings['motion_sensitivity']),
                CONFIG_KEY_SOUND_FILE: str(settings['sound_file']),
                CONFIG_KEY_IGNORE_MASK: self._serialize_mask(settings['ignore_mask']),
                CONFIG_KEY_DETECTION_MASK: self._serialize_mask(settings['detection_mask'])
            }

        try:
            secret_dir = os.path.dirname(self.secret_settings_path)
            if secret_dir:
                os.makedirs(secret_dir, exist_ok=True)
            with open(self.secret_settings_path, 'w', encoding='utf-8') as f:
                config.write(f)
        except Exception as e:
            self.message_queue.put(("error", f"Не удалось сохранить файл профилей:\n{e}"))

    def _parse_mask(self, mask_str):
        """Парсит строку маски в список прямоугольников."""
        rects = []
        if mask_str:
            try:
                for part in mask_str.split(';'):
                    if part.strip():
                        coords = list(map(int, part.strip().split(',')))
                        if len(coords) == 4:
                            rects.append(tuple(coords))
            except Exception as e:
                print(f"Ошибка загрузки маски: {e}")
        return rects

    def _serialize_mask(self, mask_list):
        """Преобразует список прямоугольников в строку маски."""
        return ';'.join(f"{x1},{y1},{x2},{y2}" for (x1, y1, x2, y2) in mask_list)

    def apply_profile(self, profile_name):
        """Применяет настройки из указанного профиля."""
        if profile_name in self.profiles:
            settings = self.profiles[profile_name]
            self.connection_mode = settings['connection_mode']
            self.camera_url = settings['camera_url']
            self.ip = settings['ip']
            self.port = settings['port']
            self.username = settings['username']
            self.password = settings['password']
            self.stream_path = settings['stream_path']
            self.motion_sensitivity = settings['motion_sensitivity']
            self.sound_file = settings['sound_file']
            self.ignore_mask_rects = settings['ignore_mask']
            self.detection_mask_rects = settings['detection_mask']
            self.current_profile_name = profile_name

            # Обновляем заголовок окна
            self.root.title(f"Nexora – {self.current_profile_name}")
            self.log_message(f"Профиль '{profile_name}' применен.")
        else:
            self.create_default_profile(profile_name)

    def create_default_profile(self, profile_name):
        """Создает новый профиль с текущими значениями."""
        self.profiles[profile_name] = {
            'connection_mode': self.connection_mode,
            'camera_url': self.camera_url,
            'ip': self.ip,
            'port': self.port,
            'username': self.username,
            'password': self.password,
            'stream_path': self.stream_path,
            'motion_sensitivity': self.motion_sensitivity,
            'sound_file': self.sound_file,
            'ignore_mask': self.ignore_mask_rects[:],
            'detection_mask': self.detection_mask_rects[:]
        }
        self.current_profile_name = profile_name
        self.save_profiles()
        self.root.title(f"Nexora – {self.current_profile_name}")
        self.log_message(f"Создан новый профиль '{profile_name}'.")

    def setup_ui(self):
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        self.btn_profiles = ttk.Button(
            btn_frame, text="Профили", command=self.open_profiles_window,
            width=12
        )
        self.btn_profiles.pack(side=tk.LEFT, padx=3)

        self.btn_start = ttk.Button(
            btn_frame, text="Старт", command=self.start_stream,
            width=12
        )
        self.btn_start.pack(side=tk.LEFT, padx=3)

        self.btn_stop = ttk.Button(
            btn_frame, text="Стоп", command=self.stop_stream,
            width=12, state=tk.DISABLED
        )
        self.btn_stop.pack(side=tk.LEFT, padx=3)

        self.btn_settings = ttk.Button(
            btn_frame, text="Настройки", command=self.open_settings_file_dialog,
            width=12
        )
        self.btn_settings.pack(side=tk.LEFT, padx=3)

        self.btn_info = ttk.Button(
            btn_frame, text="Инфо", command=self.show_info,
            width=12
        )
        self.btn_info.pack(side=tk.LEFT, padx=3)

        # СТАТУСНАЯ МЕТКА
        self.status_label = tk.Label(
            self.root,
            text=f"Активный профиль: {self.current_profile_name} | Файл настроек: {os.path.basename(self.secret_settings_path)}",
            fg="darkgreen", anchor="w"
        )
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=2)

        # Лог-панель — только одна строка (последнее сообщение)
        self.log_frame = tk.Frame(self.root)
        tk.Label(self.log_frame, text="Журнал:", anchor="w").pack(fill=tk.X)
        self.log_var = tk.StringVar()
        self.log_label = tk.Label(
            self.log_frame, textvariable=self.log_var,
            bg="#f0f0f0", anchor="w", relief="sunken", padx=5, pady=2
        )
        self.log_label.pack(fill=tk.X, expand=False)

        # ВИДЕО ЛЕЙБЛ
        self.video_label = tk.Label(self.root, text="Видео будет здесь", bg="black", fg="white")
        self.video_label.pack(expand=True, fill=tk.BOTH, padx=10, pady=5)

        self.root.bind('<Configure>', self.on_window_resize)
        self.last_width = 800
        self.last_height = 600

        # Обновляем видимость лога после инициализации
        self.update_log_visibility()

    def log_message(self, msg):
        self.log_var.set(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def process_messages(self):
        while not self.message_queue.empty():
            msg_type, text = self.message_queue.get()
            if msg_type == "error":
                messagebox.showerror("Ошибка", text)
            elif msg_type == "warning":
                messagebox.showwarning("Предупреждение", text)
            elif msg_type == "info":
                messagebox.showinfo("Информация", text)
            elif msg_type == "log":
                self.log_message(text)
        self.root.after(100, self.process_messages)

    def on_window_resize(self, event):
        if event.widget != self.root:
            return
        if event.width != self.last_width or event.height != self.last_height:
            self.last_width = event.width
            self.last_height = event.height
            if self.last_frame is not None and not self.is_running:
                self.update_frame_from_last()

    def update_frame_from_last(self):
        if self.last_frame is None:
            return
        label_width = max(1, self.video_label.winfo_width())
        label_height = max(1, self.video_label.winfo_height())
        frame_rgb = cv2.cvtColor(self.last_frame, cv2.COLOR_BGR2RGB)
        img_pil = Image.fromarray(frame_rgb)
        img_pil.thumbnail((label_width, label_height), Image.Resampling.LANCZOS)
        img_tk = ImageTk.PhotoImage(image=img_pil)
        self.video_label.config(image=img_tk, text="")
        self.video_label.image = img_tk

    def get_actual_camera_url(self):
        if self.connection_mode == 'url':
            url = self.camera_url.strip()
            return url if url not in ('', '0') else '0'
        else:
            user_pass = f"{self.username}:{self.password}@" if (self.username or self.password) else ""
            return f"rtsp://{user_pass}{self.ip}:{self.port}{self.stream_path}"

    def open_profiles_window(self):
        profiles_win = Toplevel(self.root)
        profiles_win.title("Управление профилями")
        profiles_win.geometry("700x500")
        profiles_win.resizable(False, False)
        profiles_win.transient(self.root)
        profiles_win.grab_set()

        list_frame = tk.Frame(profiles_win)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        tk.Label(list_frame, text="Список профилей:", anchor="w").pack(fill=tk.X)

        inner_frame = tk.Frame(list_frame)
        inner_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        profile_listbox = tk.Listbox(inner_frame, height=10)
        scrollbar = tk.Scrollbar(inner_frame, orient=tk.VERTICAL, command=profile_listbox.yview)
        profile_listbox.config(yscrollcommand=scrollbar.set)
        profile_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        for name in sorted(self.profiles.keys()):
            profile_listbox.insert(tk.END, name)

        try:
            current_index = list(sorted(self.profiles.keys())).index(self.current_profile_name)
            profile_listbox.selection_set(current_index)
            profile_listbox.see(current_index)
        except ValueError:
            pass

        button_frame = tk.Frame(profiles_win)
        button_frame.pack(fill=tk.X, padx=10, pady=5)

        def create_profile():
            name = tk.simpledialog.askstring("Создать профиль", "Введите имя нового профиля:")
            if not name:
                return
            if name in self.profiles:
                messagebox.showwarning("Предупреждение", f"Профиль '{name}' уже существует.")
                return
            self.create_default_profile(name)
            profile_listbox.delete(0, tk.END)
            for n in sorted(self.profiles.keys()):
                profile_listbox.insert(tk.END, n)
            self.log_message(f"Профиль '{name}' создан.")

        def edit_profile():
            selected = profile_listbox.curselection()
            if not selected:
                messagebox.showwarning("Предупреждение", "Выберите профиль для редактирования.")
                return
            name = profile_listbox.get(selected[0])
            self.open_profile_edit_window(name)

        def delete_profile():
            selected = profile_listbox.curselection()
            if not selected:
                messagebox.showwarning("Предупреждение", "Выберите профиль для удаления.")
                return
            name = profile_listbox.get(selected[0])
            if name == "Default":
                messagebox.showwarning("Предупреждение", "Нельзя удалить профиль 'Default'.")
                return
            if name == self.current_profile_name:
                messagebox.showwarning("Предупреждение", "Нельзя удалить текущий активный профиль.")
                return
            if messagebox.askyesno("Подтверждение", f"Удалить профиль '{name}'?"):
                del self.profiles[name]
                self.save_profiles()
                profile_listbox.delete(selected[0])
                self.log_message(f"Профиль '{name}' удален.")

        def use_profile():
            selected = profile_listbox.curselection()
            if not selected:
                messagebox.showwarning("Предупреждение", "Выберите профиль для использования.")
                return
            name = profile_listbox.get(selected[0])
            self.apply_profile(name)
            profile_listbox.selection_clear(0, tk.END)
            try:
                index = list(sorted(self.profiles.keys())).index(self.current_profile_name)
                profile_listbox.selection_set(index)
            except ValueError:
                pass
            self.log_message(f"Профиль '{name}' установлен как активный.")
            profiles_win.destroy()

        tk.Button(button_frame, text="Создать", command=create_profile, width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="Редактировать", command=edit_profile, width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="Удалить", command=delete_profile, width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="Использовать", command=use_profile, width=15, bg="lightgreen").pack(side=tk.LEFT,
                                                                                                          padx=5)

    def open_profile_edit_window(self, profile_name):
        """Открывает окно редактирования конкретного профиля с вкладкой зон детекции."""
        if profile_name not in self.profiles:
            messagebox.showerror("Ошибка", f"Профиль '{profile_name}' не найден.")
            return

        settings_win = Toplevel(self.root)
        settings_win.title(f"Редактирование профиля: {profile_name}")
        settings_win.geometry("600x700")
        settings_win.resizable(False, False)
        settings_win.transient(self.root)
        settings_win.grab_set()

        profile_settings = self.profiles[profile_name]

        mode_var = tk.StringVar(value=profile_settings['connection_mode'])
        url_var = tk.StringVar(value=str(profile_settings['camera_url']))
        ip_var = tk.StringVar(value=profile_settings['ip'])
        port_var = tk.StringVar(value=profile_settings['port'])
        user_var = tk.StringVar(value=profile_settings['username'])
        pass_var = tk.StringVar(value=profile_settings['password'])
        stream_path_var = tk.StringVar(value=profile_settings['stream_path'])
        sens_var = tk.IntVar(value=profile_settings['motion_sensitivity'])
        sound_file_var = tk.StringVar(value=profile_settings['sound_file'])

        notebook = ttk.Notebook(settings_win)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Вкладка подключения
        conn_frame = ttk.Frame(notebook)
        notebook.add(conn_frame, text="Подключение")

        tk.Label(conn_frame, text="Метод подключения:", anchor="w").pack(fill=tk.X, padx=20, pady=(10, 5))
        radio_frame = tk.Frame(conn_frame)
        radio_frame.pack(fill=tk.X, padx=20)
        tk.Radiobutton(
            radio_frame, text="Прямой URL", variable=mode_var, value='url',
            command=lambda: self.toggle_connection_mode('url', url_frame, params_frame)
        ).pack(side=tk.LEFT)
        tk.Radiobutton(
            radio_frame, text="Параметры камеры", variable=mode_var, value='params',
            command=lambda: self.toggle_connection_mode('params', url_frame, params_frame)
        ).pack(side=tk.LEFT, padx=(20, 0))

        url_frame = tk.Frame(conn_frame)
        tk.Label(url_frame, text="URL видеопотока (0 — веб-камера):").pack(anchor="w", padx=20)
        tk.Entry(url_frame, textvariable=url_var, width=60).pack(fill=tk.X, pady=(5, 0), padx=20)

        params_frame = tk.Frame(conn_frame)
        tk.Label(params_frame, text="IP-адрес:", anchor="w").grid(row=0, column=0, sticky="w", padx=(20, 5), pady=2)
        tk.Entry(params_frame, textvariable=ip_var, width=20).grid(row=0, column=1, sticky="w", pady=2)
        tk.Label(params_frame, text="Порт:", anchor="w").grid(row=1, column=0, sticky="w", padx=(20, 5), pady=2)
        tk.Entry(params_frame, textvariable=port_var, width=20).grid(row=1, column=1, sticky="w", pady=2)
        tk.Label(params_frame, text="Логин:", anchor="w").grid(row=2, column=0, sticky="w", padx=(20, 5), pady=2)
        tk.Entry(params_frame, textvariable=user_var, width=20).grid(row=2, column=1, sticky="w", pady=2)
        tk.Label(params_frame, text="Пароль:", anchor="w").grid(row=3, column=0, sticky="w", padx=(20, 5), pady=2)
        tk.Entry(params_frame, textvariable=pass_var, width=20, show="*").grid(row=3, column=1, sticky="w", pady=2)
        tk.Label(params_frame, text="Путь потока:", anchor="w").grid(row=4, column=0, sticky="w", padx=(20, 5), pady=2)
        tk.Entry(params_frame, textvariable=stream_path_var, width=20).grid(row=4, column=1, sticky="w", pady=2)

        if mode_var.get() == 'url':
            url_frame.pack(fill=tk.X, padx=20, pady=5)
        else:
            params_frame.pack(fill=tk.X, padx=20, pady=5)

        tk.Frame(conn_frame, height=2, bg="gray").pack(fill=tk.X, padx=20, pady=10)

        tk.Label(conn_frame, text="Чувствительность движения:", anchor="w").pack(fill=tk.X, padx=20)
        sens_value_label = tk.Label(conn_frame, text=f"Текущее значение: {sens_var.get()}")
        sens_value_label.pack(pady=(0, 5))
        sens_scale = tk.Scale(
            conn_frame,
            from_=50,
            to=5000,
            orient=tk.HORIZONTAL,
            variable=sens_var,
            length=400,
            resolution=10,
            command=lambda val: sens_value_label.config(text=f"Текущее значение: {val}")
        )
        sens_scale.pack(pady=5)

        # Вкладка звука
        sound_frame = ttk.Frame(notebook)
        notebook.add(sound_frame, text="Звук")

        tk.Label(sound_frame, text="Звук при детекции движения:", anchor="w").pack(fill=tk.X, padx=20, pady=(10, 5))
        sound_entry = tk.Entry(sound_frame, textvariable=sound_file_var, state='readonly')
        sound_entry.pack(fill=tk.X, padx=20, pady=5)

        def choose_sound():
            path = filedialog.askopenfilename(
                title="Выберите звуковой файл (.wav)",
                filetypes=[("WAV files", "*.wav"), ("All files", "*.*")]
            )
            if path:
                sound_file_var.set(path)

        tk.Button(sound_frame, text="Обзор...", command=choose_sound).pack(pady=5)

        # Вкладка зон детекции
        zones_frame = ttk.Frame(notebook)
        notebook.add(zones_frame, text="Зоны")

        def open_zones_editor():
            # Проверяем, запущен ли поток
            if not self.is_running:
                # Проверяем, есть ли кадр, если нет - запускаем на короткое время
                if self.last_frame is None:
                    # Временно запускаем поток, чтобы получить кадр
                    self.message_queue.put(("log", "Получение кадра для настройки зон..."))
                    # Блокируем кнопки управления потоком
                    self.btn_start.config(state=tk.DISABLED)
                    self.btn_stop.config(state=tk.DISABLED)

                    # Запускаем поток получения кадра
                    threading.Thread(target=self._temp_capture_for_zones, args=(settings_win,), daemon=True).start()
                    return  # Выходим, дальше выполнится из _temp_capture_for_zones
                else:
                    # Кадр есть, открываем редактор
                    self._open_zones_editor_internal(settings_win, profile_name)
            else:
                # Поток уже запущен, кадр должен быть
                if self.last_frame is not None:
                    self._open_zones_editor_internal(settings_win, profile_name)
                else:
                    messagebox.showwarning("Предупреждение",
                                           "Нет доступного кадра для настройки зон детекции.\nЗапустите поток хотя бы на мгновение.")
                    return

        tk.Button(zones_frame, text="Настроить зоны детекции", command=open_zones_editor, width=30, height=2).pack(
            pady=20)

        # Кнопки сохранения
        btn_frame = tk.Frame(settings_win)
        btn_frame.pack(pady=15)

        def apply_and_close():
            self.profiles[profile_name] = {
                'connection_mode': mode_var.get(),
                'camera_url': url_var.get(),
                'ip': ip_var.get(),
                'port': port_var.get(),
                'username': user_var.get(),
                'password': pass_var.get(),
                'stream_path': stream_path_var.get(),
                'motion_sensitivity': sens_var.get(),
                'sound_file': sound_file_var.get(),
                'ignore_mask': self.profiles[profile_name].get('ignore_mask', []),
                'detection_mask': self.profiles[profile_name].get('detection_mask', [])
            }
            self.save_profiles()
            settings_win.destroy()
            self.log_message(f"Профиль '{profile_name}' сохранен.")

        tk.Button(btn_frame, text="Сохранить", command=apply_and_close, width=10).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Отмена", command=settings_win.destroy, width=10).pack(side=tk.LEFT, padx=5)

    def _temp_capture_for_zones(self, settings_win):
        """Внутренний метод для получения кадра, если поток не запущен."""
        actual_url = self.get_actual_camera_url()
        temp_cap = cv2.VideoCapture(actual_url)
        temp_cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        try:
            if not temp_cap.isOpened():
                self.message_queue.put(("error", "Не удалось подключиться к камере для получения кадра."))
                return
            ret, frame = temp_cap.read()
            if ret and frame is not None:
                self.last_frame = frame.copy()
                self.message_queue.put(("log", "Кадр получен. Открываю редактор зон..."))
                # Вызываем открытие редактора из основного потока
                self.root.after(0, self._open_zones_editor_internal, settings_win, self.current_profile_name)
            else:
                self.message_queue.put(("error", "Не удалось получить кадр с камеры."))
        except Exception as e:
            self.message_queue.put(("error", f"Ошибка при получении кадра:\n{str(e)}"))
        finally:
            if temp_cap:
                temp_cap.release()
            # Возвращаем кнопки в исходное состояние
            self.root.after(0, lambda: self.btn_start.config(state=tk.NORMAL if not self.is_running else tk.DISABLED))
            self.root.after(0, lambda: self.btn_stop.config(state=tk.NORMAL if self.is_running else tk.DISABLED))

    def _open_zones_editor_internal(self, settings_win, profile_name):
        """Внутренняя логика открытия окна редактирования зон."""
        if self.last_frame is None:
            messagebox.showwarning("Предупреждение",
                                   "Нет доступного кадра для настройки зон детекции.\nЗапустите поток хотя бы на мгновение.")
            return

        # Используем временные переменные из профиля
        temp_ignore = self.profiles[profile_name].get('ignore_mask', [])
        temp_detect = self.profiles[profile_name].get('detection_mask', [])

        detection_win = Toplevel(settings_win)
        detection_win.title("Зоны детекции/игнорирования")
        detection_win.geometry("800x700")
        detection_win.transient(settings_win)
        detection_win.grab_set()

        orig_h, orig_w = self.last_frame.shape[:2]
        canvas_frame = tk.Frame(detection_win)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        canvas = tk.Canvas(canvas_frame, bg="black", highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)

        scale = 1.0
        offset_x = 0
        offset_y = 0
        canvas_img = None
        displayed_ignore_rects = []
        displayed_detect_rects = []

        zone_type_var = tk.StringVar(value="ignore")
        rect_id = None
        start_x = start_y = 0

        def redraw_canvas():
            nonlocal canvas_img, scale, offset_x, offset_y, displayed_ignore_rects, displayed_detect_rects
            canvas.delete("all")
            displayed_ignore_rects.clear()
            displayed_detect_rects.clear()

            cw = canvas.winfo_width()
            ch = canvas.winfo_height()
            if cw <= 1 or ch <= 1:
                return

            scale_w = cw / orig_w
            scale_h = ch / orig_h
            scale = min(scale_w, scale_h)
            new_w = int(orig_w * scale)
            new_h = int(orig_h * scale)
            offset_x = (cw - new_w) // 2
            offset_y = (ch - new_h) // 2

            frame_rgb = cv2.cvtColor(self.last_frame, cv2.COLOR_BGR2RGB)
            img_pil = Image.fromarray(frame_rgb)
            img_resized = img_pil.resize((new_w, new_h), Image.Resampling.LANCZOS)
            canvas_img = ImageTk.PhotoImage(img_resized)
            canvas.create_image(offset_x, offset_y, anchor=tk.NW, image=canvas_img)

            for (x1, y1, x2, y2) in temp_ignore:
                sx1 = offset_x + x1 * scale
                sy1 = offset_y + y1 * scale
                sx2 = offset_x + x2 * scale
                sy2 = offset_y + y2 * scale
                rect_id = canvas.create_rectangle(sx1, sy1, sx2, sy2, outline='yellow', width=2, stipple='gray50')
                displayed_ignore_rects.append(rect_id)

            for (x1, y1, x2, y2) in temp_detect:
                sx1 = offset_x + x1 * scale
                sy1 = offset_y + y1 * scale
                sx2 = offset_x + x2 * scale
                sy2 = offset_y + y2 * scale
                rect_id = canvas.create_rectangle(sx1, sy1, sx2, sy2, outline='blue', width=2, stipple='gray50')
                displayed_detect_rects.append(rect_id)

        detection_win.update_idletasks()
        redraw_canvas()

        def canvas_to_frame_coords(cx, cy):
            fx = max(0, min(orig_w - 1, int((cx - offset_x) / scale)))
            fy = max(0, min(orig_h - 1, int((cy - offset_y) / scale)))
            return fx, fy

        def on_button_press(event):
            nonlocal start_x, start_y, rect_id
            start_x, start_y = event.x, event.y
            if rect_id:
                canvas.delete(rect_id)
            color = 'red' if zone_type_var.get() == 'ignore' else 'cyan'
            rect_id = canvas.create_rectangle(start_x, start_y, start_x, start_y, outline=color, width=2)

        def on_mouse_move(event):
            nonlocal rect_id
            if rect_id:
                canvas.coords(rect_id, start_x, start_y, event.x, event.y)

        def on_button_release(event):
            nonlocal rect_id
            if rect_id:
                x1_canvas, y1_canvas = start_x, start_y
                x2_canvas, y2_canvas = event.x, event.y

                fx1, fy1 = canvas_to_frame_coords(x1_canvas, y1_canvas)
                fx2, fy2 = canvas_to_frame_coords(x2_canvas, y2_canvas)

                fx1, fx2 = sorted([fx1, fx2])
                fy1, fy2 = sorted([fy1, fy2])

                if fx2 - fx1 < 5 or fy2 - fy1 < 5:
                    canvas.delete(rect_id)
                    rect_id = None
                    return

                if zone_type_var.get() == 'ignore':
                    temp_ignore.append((fx1, fy1, fx2, fy2))
                else:
                    temp_detect.append((fx1, fy1, fx2, fy2))

                redraw_canvas()
                rect_id = None

        canvas.bind("<ButtonPress-1>", on_button_press)
        canvas.bind("<B1-Motion>", on_mouse_move)
        canvas.bind("<ButtonRelease-1>", on_button_release)

        control_frame = tk.Frame(detection_win)
        control_frame.pack(pady=10)

        def clear_all_ignore():
            temp_ignore.clear()
            redraw_canvas()

        def clear_all_detect():
            temp_detect.clear()
            redraw_canvas()

        def undo_last():
            zone_type = zone_type_var.get()
            if zone_type == 'ignore' and temp_ignore:
                temp_ignore.pop()
                self.log_message("Отменена последняя зона исключения.")
            elif zone_type == 'detect' and temp_detect:
                temp_detect.pop()
                self.log_message("Отменена последняя зона детекции.")
            else:
                self.log_message("Нет зон для отмены этого типа.")
            redraw_canvas()

        def apply_and_close():
            self.profiles[profile_name]['ignore_mask'] = temp_ignore[:]
            self.profiles[profile_name]['detection_mask'] = temp_detect[:]
            self.save_profiles()
            detection_win.destroy()

        tk.Button(control_frame, text="Очистить исключения", command=clear_all_ignore).pack(side=tk.LEFT, padx=5)
        tk.Button(control_frame, text="Очистить детекции", command=clear_all_detect).pack(side=tk.LEFT, padx=5)
        tk.Button(control_frame, text="Отменить", command=undo_last).pack(side=tk.LEFT, padx=5)
        tk.Button(control_frame, text="Применить", command=apply_and_close, bg="lightgreen").pack(side=tk.LEFT, padx=5)
        tk.Button(control_frame, text="Отмена", command=detection_win.destroy).pack(side=tk.LEFT, padx=5)

        radio_frame = tk.Frame(detection_win)
        radio_frame.pack(pady=5)
        tk.Radiobutton(radio_frame, text="Исключения (желтый)", variable=zone_type_var, value='ignore').pack(
            side=tk.LEFT)
        tk.Radiobutton(radio_frame, text="Детекции (голубой)", variable=zone_type_var, value='detect').pack(
            side=tk.LEFT, padx=(20, 0))
        tk.Label(detection_win, text="Нарисуйте прямоугольники — выберите тип выше", fg="blue").pack(pady=(5, 0))

        def on_resize(event):
            if event.widget == detection_win:
                detection_win.after(50, redraw_canvas)

        detection_win.bind("<Configure>", on_resize)

    def toggle_connection_mode(self, mode, url_frame, params_frame):
        if mode == 'url':
            url_frame.pack(fill=tk.X, padx=20, pady=5)
            params_frame.pack_forget()
        else:
            url_frame.pack_forget()
            params_frame.pack(fill=tk.X, padx=20, pady=5)

    def show_info(self):
        info_text = (
            f"Программа Nexora {APP_VERSION}\n"
            f"Автор: {AUTHOR}\n"
            "Основные функции:\n"
            "• Поддержка подключения к IP-камерам по RTSP/HTTP или к встроенной веб-камере.\n"
            "• Обнаружение движения на основе анализа изменений в кадре.\n"
            "• Настройка чувствительности детектора движения.\n"
            "• Возможность задать зоны игнорирования и активной детекции движения.\n"
            "• Воспроизведение звука при срабатывании.\n"
            "• Сохранение и загрузка конфигураций подключения в файл (Профили).\n"
            "• Отображение статуса подключения и журнала событий.\n"
            "• Простой и интуитивно понятный интерфейс.\n"
            "Рекомендации:\n"
            "• Для IP-камер укажите корректные IP, порт, логин и путь потока.\n"
            "• При использовании веб-камеры введите '0' в поле URL.\n"
            "• Настройки сохраняются автоматически в выбранный INI-файл."
        )
        messagebox.showinfo("О программе", info_text)

    def start_stream(self):
        if self.is_running:
            return
        self.is_running = True
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self.status_label.config(text="Статус: запуск...", fg="orange")
        self.message_queue.put(("log", "Запуск видеопотока..."))
        threading.Thread(target=self.video_loop, daemon=True).start()

    def stop_stream(self):
        self.is_running = False
        self.message_queue.put(("log", "Остановка видеопотока..."))

    def _finalize_stop(self):
        if self.cap:
            self.cap.release()
            self.cap = None
        self.is_running = False
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        self.video_label.config(image='', text="Видео остановлено")
        self.status_label.config(
            text=f"Активный профиль: {self.current_profile_name} | Файл настроек: {os.path.basename(self.secret_settings_path)}",
            fg="darkgreen")
        self.message_queue.put(("log", "Видеопоток остановлен"))

    def show_motion_alert(self):
        if self.alert_window and self.alert_window.winfo_exists():
            self.alert_window.destroy()

        self.alert_window = Toplevel(self.root)
        self.alert_window.title("⚠️ Движение!")
        self.alert_window.geometry("300x120")
        self.alert_window.resizable(False, False)
        self.alert_window.transient(self.root)
        self.alert_window.grab_set()
        self.alert_window.protocol("WM_DELETE_WINDOW", lambda: self.alert_window.destroy())

        tk.Label(
            self.alert_window,
            text="⚠️ ОБНАРУЖЕНО ДВИЖЕНИЕ! ⚠️",
            font=("Arial", 12, "bold"),
            fg="red",
            pady=20
        ).pack()

        tk.Button(
            self.alert_window,
            text="OK",
            command=self.alert_window.destroy,
            width=10
        ).pack()

        if self.sound_file and os.path.exists(self.sound_file):
            try:
                winsound.PlaySound(self.sound_file, winsound.SND_FILENAME | winsound.SND_ASYNC)
            except Exception as e:
                self.message_queue.put(("log", f"Не удалось воспроизвести звук: {e}"))

        self.root.after(3000, self._auto_close_alert_window)

    def _auto_close_alert_window(self):
        if self.alert_window and self.alert_window.winfo_exists():
            self.alert_window.destroy()

    def on_closing(self):
        self.stop_stream()
        time.sleep(0.2)
        self.root.destroy()

    def video_loop(self):
        actual_url = self.get_actual_camera_url()
        self.cap = cv2.VideoCapture(actual_url)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        try:
            if not self.cap.isOpened():
                self.message_queue.put(("error", "Не удалось подключиться к камере"))
                return

            self.message_queue.put(("log", f"Подключено к: {actual_url}"))
            self.root.after(0, lambda: self.status_label.config(text="Статус: работает", fg="green"))

            ret, first_frame = self.cap.read()
            if not ret or first_frame is None:
                self.message_queue.put(("error", "Пустой кадр. Проверьте камеру."))
                return

            gray_first = cv2.cvtColor(first_frame, cv2.COLOR_BGR2GRAY)
            gray_first = cv2.GaussianBlur(gray_first, (21, 21), 0)

            motion_detected_recently = False
            last_time = time.time()
            target_fps = 30
            frame_interval = 1.0 / target_fps

            while self.is_running:
                current_time = time.time()
                if current_time - last_time < frame_interval:
                    time.sleep(0.001)
                    continue
                last_time = current_time

                ret, frame = self.cap.read()
                if not ret:
                    self.message_queue.put(("log", "Потеря видеопотока"))
                    break

                self.last_frame = frame.copy()

                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (21, 21), 0)

                delta = cv2.absdiff(gray_first, gray)
                thresh = cv2.threshold(delta, 25, 255, cv2.THRESH_BINARY)[1]
                thresh = cv2.dilate(thresh, None, iterations=2)

                contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                motion_detected = False
                for contour in contours:
                    if cv2.contourArea(contour) < self.motion_sensitivity:
                        continue

                    x, y, w, h = cv2.boundingRect(contour)
                    cx, cy = x + w // 2, y + h // 2
                    contour_bbox = (x, y, x + w, y + h)

                    in_detection_zone = False
                    if not self.detection_mask_rects:
                        in_detection_zone = True
                    else:
                        for (dx1, dy1, dx2, dy2) in self.detection_mask_rects:
                            if not (contour_bbox[2] < dx1 or contour_bbox[0] > dx2 or
                                    contour_bbox[3] < dy1 or contour_bbox[1] > dy2):
                                in_detection_zone = True
                                break

                    in_ignored_zone = False
                    for (ix1, iy1, ix2, iy2) in self.ignore_mask_rects:
                        if not (contour_bbox[2] < ix1 or contour_bbox[0] > ix2 or
                                contour_bbox[3] < iy1 or contour_bbox[1] > iy2):
                            in_ignored_zone = True
                            break

                    if in_detection_zone and not in_ignored_zone:
                        motion_detected = True
                        break

                if motion_detected and not motion_detected_recently:
                    self.show_motion_alert()
                    motion_detected_recently = True
                elif not motion_detected:
                    motion_detected_recently = False

                label_width = max(1, self.video_label.winfo_width())
                label_height = max(1, self.video_label.winfo_height())
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img_pil = Image.fromarray(frame_rgb)
                img_pil.thumbnail((label_width, label_height), Image.Resampling.LANCZOS)

                status_text = "DETECTION" if motion_detected else "Green"
                color = (255, 0, 0) if motion_detected else (0, 255, 0)
                draw = ImageDraw.Draw(img_pil)
                try:
                    font = ImageFont.truetype("arialbd.ttf", 36)
                except:
                    try:
                        font = ImageFont.truetype("arial.ttf", 32)
                    except:
                        font = ImageFont.load_default()
                text_bbox = draw.textbbox((10, 10), status_text, font=font)
                draw.rectangle(text_bbox, fill=(0, 0, 0, 200))
                draw.text((10, 10), status_text, fill=color, font=font)

                img_tk = ImageTk.PhotoImage(image=img_pil)
                self.root.after(0, self.update_frame, img_tk)

        except Exception as e:
            self.message_queue.put(("error", f"Ошибка в видеопотоке:\n{str(e)}"))
        finally:
            self.root.after(0, self._finalize_stop)

    def update_frame(self, img_tk):
        if self.is_running:
            self.video_label.config(image=img_tk, text="")
            self.video_label.image = img_tk


if __name__ == "__main__":
    root = tk.Tk()
    app = CameraApp(root)
    root.mainloop()