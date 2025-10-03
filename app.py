import tkinter as tk
from tkinter import messagebox, filedialog, Toplevel, ttk
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
CONFIG_KEY_IGNORE_MASK = 'ignore_mask'  # Новое: зоны игнорирования

SECRET_CONFIG_SECTION = 'SecretPaths'
SECRET_CONFIG_KEY_PATH = 'secret_path'

APP_VERSION = "v0.1"
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

        self.connection_mode = 'url'
        self.camera_url = '0'
        self.ip = '192.168.1.64'
        self.port = '554'
        self.username = 'admin'
        self.password = ''
        self.stream_path = '/stream1'
        self.motion_sensitivity = MOTION_DEFAULT_SENSITIVITY
        self.ignore_mask_rects = []  # [(x1, y1, x2, y2), ...] — в координатах оригинального кадра
        self.sound_file = ""
        self.alert_window = None  # Для замены предыдущего окна предупреждения

        self.is_running = False
        self.cap = None
        self.last_frame = None
        self.message_queue = Queue()

        self.load_main_settings()
        self.load_secret_settings()
        self.setup_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.after(100, self.process_messages)

    def load_main_settings(self):
        config = configparser.ConfigParser()
        if os.path.exists(self.main_settings_path):
            config.read(self.main_settings_path, encoding='utf-8')
            if SECRET_CONFIG_SECTION in config:
                self.secret_settings_path = config[SECRET_CONFIG_SECTION].get(SECRET_CONFIG_KEY_PATH, '')

        if not self.secret_settings_path or not os.path.exists(self.secret_settings_path):
            default_secret = os.path.expanduser("~/nexora_secret_settings.ini")
            self.secret_settings_path = default_secret
            self.save_main_settings()

    def save_main_settings(self):
        config = configparser.ConfigParser()
        config[SECRET_CONFIG_SECTION] = {
            SECRET_CONFIG_KEY_PATH: self.secret_settings_path
        }
        try:
            with open(self.main_settings_path, 'w', encoding='utf-8') as f:
                config.write(f)
        except Exception as e:
            self.message_queue.put(("error", f"Не удалось сохранить основной файл настроек:\n{e}"))

    def load_secret_settings(self):
        config = configparser.ConfigParser()
        if os.path.exists(self.secret_settings_path):
            config.read(self.secret_settings_path, encoding='utf-8')
            if CONFIG_SECTION in config:
                self.connection_mode = config[CONFIG_SECTION].get(CONFIG_KEY_CONNECTION_MODE, 'url')
                self.camera_url = config[CONFIG_SECTION].get(CONFIG_KEY_URL, '0')
                self.ip = config[CONFIG_SECTION].get(CONFIG_KEY_IP, '192.168.1.64')
                self.port = config[CONFIG_SECTION].get(CONFIG_KEY_PORT, '554')
                self.username = config[CONFIG_SECTION].get(CONFIG_KEY_USERNAME, 'admin')
                self.password = config[CONFIG_SECTION].get(CONFIG_KEY_PASSWORD, '')
                self.stream_path = config[CONFIG_SECTION].get(CONFIG_KEY_STREAM_PATH, '/stream1')
                self.motion_sensitivity = config[CONFIG_SECTION].getint(
                    CONFIG_KEY_MOTION_SENSITIVITY, MOTION_DEFAULT_SENSITIVITY
                )
                self.sound_file = config[CONFIG_SECTION].get('sound_file', '')
                mask_str = config[CONFIG_SECTION].get(CONFIG_KEY_IGNORE_MASK, '')
                self.ignore_mask_rects = []
                if mask_str:
                    try:
                        rects = []
                        for part in mask_str.split(';'):
                            if part.strip():
                                coords = list(map(int, part.strip().split(',')))
                                if len(coords) == 4:
                                    rects.append(tuple(coords))
                        self.ignore_mask_rects = rects
                    except Exception as e:
                        print(f"Ошибка загрузки маски: {e}")
        else:
            self.save_secret_settings()

    def save_secret_settings(self):
        config = configparser.ConfigParser()
        config[CONFIG_SECTION] = {
            CONFIG_KEY_CONNECTION_MODE: self.connection_mode,
            CONFIG_KEY_URL: str(self.camera_url),
            CONFIG_KEY_IP: str(self.ip),
            CONFIG_KEY_PORT: str(self.port),
            CONFIG_KEY_USERNAME: str(self.username),
            CONFIG_KEY_PASSWORD: str(self.password),
            CONFIG_KEY_STREAM_PATH: str(self.stream_path),
            CONFIG_KEY_MOTION_SENSITIVITY: str(self.motion_sensitivity),
            'sound_file': str(self.sound_file),
            CONFIG_KEY_IGNORE_MASK: ';'.join(
                f"{x1},{y1},{x2},{y2}" for (x1, y1, x2, y2) in self.ignore_mask_rects
            )
        }
        try:
            secret_dir = os.path.dirname(self.secret_settings_path)
            if secret_dir:
                os.makedirs(secret_dir, exist_ok=True)
            with open(self.secret_settings_path, 'w', encoding='utf-8') as f:
                config.write(f)
        except Exception as e:
            self.message_queue.put(("error", f"Не удалось сохранить настройки:\n{e}"))

    def setup_ui(self):
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        self.btn_settings = ttk.Button(
            btn_frame, text="Настройки", command=self.open_settings_window,
            width=12
        )
        self.btn_settings.pack(side=tk.LEFT, padx=3)

        self.btn_detection = ttk.Button(
            btn_frame, text="Детекции", command=self.open_detection_window,
            width=12
        )
        self.btn_detection.pack(side=tk.LEFT, padx=3)

        self.btn_sound = ttk.Button(
            btn_frame, text="Звук", command=self.open_sound_settings,
            width=12
        )
        self.btn_sound.pack(side=tk.LEFT, padx=3)

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

        self.btn_info = ttk.Button(
            btn_frame, text="Инфо", command=self.show_info,
            width=12
        )
        self.btn_info.pack(side=tk.LEFT, padx=3)

        self.status_label = tk.Label(
            self.root, text=f"Настройки: {self.secret_settings_path}", fg="blue", anchor="w"
        )
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=2)

        # Лог-панель — только одна строка (последнее сообщение)
        log_frame = tk.Frame(self.root)
        log_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 5))
        tk.Label(log_frame, text="Журнал:", anchor="w").pack(fill=tk.X)
        self.log_var = tk.StringVar()
        self.log_label = tk.Label(
            log_frame, textvariable=self.log_var,
            bg="#f0f0f0", anchor="w", relief="sunken", padx=5, pady=2
        )
        self.log_label.pack(fill=tk.X, expand=False)

        self.video_label = tk.Label(self.root, text="Видео будет здесь", bg="black", fg="white")
        self.video_label.pack(expand=True, fill=tk.BOTH, padx=10, pady=5)

        self.root.bind('<Configure>', self.on_window_resize)
        self.last_width = 800
        self.last_height = 600

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

    def choose_secret_path(self, path_var, entry_widget, settings_win):
        """Выбор файла настроек. Если файл существует — загружаем его содержимое в форму."""
        current = path_var.get()
        initial_dir = os.path.dirname(current) if os.path.exists(current) else os.path.expanduser("~")
        initial_file = os.path.basename(current) if os.path.exists(current) else "nexora_secret_settings.ini"

        path = filedialog.asksaveasfilename(
            title="Выберите файл для хранения настроек подключения",
            defaultextension=".ini",
            filetypes=[("INI files", "*.ini"), ("All files", "*.*")],
            initialdir=initial_dir,
            initialfile=initial_file
        )
        if path:
            path_var.set(path)
            entry_widget.config(state='normal')
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, path)
            entry_widget.config(state='readonly')

            # Если файл существует — загружаем настройки в форму
            if os.path.exists(path):
                self.load_settings_into_form(path, settings_win)

    def load_settings_into_form(self, path, settings_win):
        """Загружает настройки из INI-файла и обновляет поля в окне настроек."""
        config = configparser.ConfigParser()
        try:
            config.read(path, encoding='utf-8')
            if CONFIG_SECTION in config:
                mode = config[CONFIG_SECTION].get(CONFIG_KEY_CONNECTION_MODE, 'url')
                url = config[CONFIG_SECTION].get(CONFIG_KEY_URL, '0')
                ip = config[CONFIG_SECTION].get(CONFIG_KEY_IP, '192.168.1.64')
                port = config[CONFIG_SECTION].get(CONFIG_KEY_PORT, '554')
                username = config[CONFIG_SECTION].get(CONFIG_KEY_USERNAME, 'admin')
                password = config[CONFIG_SECTION].get(CONFIG_KEY_PASSWORD, '')
                stream_path = config[CONFIG_SECTION].get(CONFIG_KEY_STREAM_PATH, '/stream1')
                sensitivity = config[CONFIG_SECTION].getint(CONFIG_KEY_MOTION_SENSITIVITY, MOTION_DEFAULT_SENSITIVITY)

                # Обновляем переменные
                settings_win.mode_var.set(mode)
                settings_win.url_var.set(url)
                settings_win.ip_var.set(ip)
                settings_win.port_var.set(port)
                settings_win.user_var.set(username)
                settings_win.pass_var.set(password)
                settings_win.stream_path_var.set(stream_path)
                settings_win.sens_var.set(sensitivity)

                # Обновляем отображение фреймов
                if mode == 'url':
                    settings_win.url_frame.pack(fill=tk.X, padx=20, pady=5)
                    settings_win.params_frame.pack_forget()
                else:
                    settings_win.url_frame.pack_forget()
                    settings_win.params_frame.pack(fill=tk.X, padx=20, pady=5)

                # Обновляем метку чувствительности
                settings_win.sens_value_label.config(text=f"Текущее значение: {sensitivity}")

        except Exception as e:
            self.message_queue.put(("error", f"Не удалось загрузить настройки из файла:\n{e}"))

    def toggle_connection_mode(self, mode, url_frame, params_frame):
        if mode == 'url':
            url_frame.pack(fill=tk.X, padx=20, pady=5)
            params_frame.pack_forget()
        else:
            url_frame.pack_forget()
            params_frame.pack(fill=tk.X, padx=20, pady=5)

    def open_settings_window(self):
        settings_win = Toplevel(self.root)
        settings_win.title("Настройки подключения")
        settings_win.geometry("500x600")
        settings_win.resizable(False, False)
        settings_win.transient(self.root)
        settings_win.grab_set()

        # Переменные для привязки к виджетам
        secret_path_var = tk.StringVar(value=self.secret_settings_path)
        mode_var = tk.StringVar(value=self.connection_mode)
        url_var = tk.StringVar(value=str(self.camera_url))
        ip_var = tk.StringVar(value=self.ip)
        port_var = tk.StringVar(value=self.port)
        user_var = tk.StringVar(value=self.username)
        pass_var = tk.StringVar(value=self.password)
        stream_path_var = tk.StringVar(value=self.stream_path)
        sens_var = tk.IntVar(value=self.motion_sensitivity)

        # Сохраняем ссылки в окне для удобства доступа
        settings_win.mode_var = mode_var
        settings_win.url_var = url_var
        settings_win.ip_var = ip_var
        settings_win.port_var = port_var
        settings_win.user_var = user_var
        settings_win.pass_var = pass_var
        settings_win.stream_path_var = stream_path_var
        settings_win.sens_var = sens_var

        # Путь к файлу настроек
        tk.Label(settings_win, text="Файл настроек подключения:", anchor="w").pack(fill=tk.X, padx=20, pady=(10, 5))
        secret_frame = tk.Frame(settings_win)
        secret_frame.pack(fill=tk.X, padx=20)
        secret_entry = tk.Entry(secret_frame, textvariable=secret_path_var, state='readonly')
        secret_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(
            secret_frame, text="Обзор...",
            command=lambda: self.choose_secret_path(secret_path_var, secret_entry, settings_win),
            width=8
        ).pack(side=tk.RIGHT, padx=(5, 0))

        tk.Frame(settings_win, height=2, bg="gray").pack(fill=tk.X, padx=20, pady=10)

        # Метод подключения
        tk.Label(settings_win, text="Метод подключения:", anchor="w").pack(fill=tk.X, padx=20)
        radio_frame = tk.Frame(settings_win)
        radio_frame.pack(fill=tk.X, padx=20, pady=5)
        tk.Radiobutton(
            radio_frame, text="Прямой URL", variable=mode_var, value='url',
            command=lambda: self.toggle_connection_mode('url', settings_win.url_frame, settings_win.params_frame)
        ).pack(side=tk.LEFT)
        tk.Radiobutton(
            radio_frame, text="Параметры камеры", variable=mode_var, value='params',
            command=lambda: self.toggle_connection_mode('params', settings_win.url_frame, settings_win.params_frame)
        ).pack(side=tk.LEFT, padx=(20, 0))

        # URL-фрейм
        url_frame = tk.Frame(settings_win)
        tk.Label(url_frame, text="URL видеопотока (0 — веб-камера):").pack(anchor="w")
        tk.Entry(url_frame, textvariable=url_var).pack(fill=tk.X, pady=(5, 0))

        # Параметры камеры
        params_frame = tk.Frame(settings_win)
        tk.Label(params_frame, text="IP-адрес:").grid(row=0, column=0, sticky="w", pady=2)
        tk.Entry(params_frame, textvariable=ip_var, width=20).grid(row=0, column=1, padx=(10, 0), pady=2)

        tk.Label(params_frame, text="Порт:").grid(row=1, column=0, sticky="w", pady=2)
        tk.Entry(params_frame, textvariable=port_var, width=20).grid(row=1, column=1, padx=(10, 0), pady=2)

        tk.Label(params_frame, text="Логин:").grid(row=2, column=0, sticky="w", pady=2)
        tk.Entry(params_frame, textvariable=user_var, width=20).grid(row=2, column=1, padx=(10, 0), pady=2)

        tk.Label(params_frame, text="Пароль:").grid(row=3, column=0, sticky="w", pady=2)
        tk.Entry(params_frame, textvariable=pass_var, width=20, show="*").grid(row=3, column=1, padx=(10, 0), pady=2)

        tk.Label(params_frame, text="Путь потока:").grid(row=4, column=0, sticky="w", pady=2)
        tk.Entry(params_frame, textvariable=stream_path_var, width=20).grid(row=4, column=1, padx=(10, 0), pady=2)

        settings_win.url_frame = url_frame
        settings_win.params_frame = params_frame

        if mode_var.get() == 'url':
            url_frame.pack(fill=tk.X, padx=20, pady=5)
        else:
            params_frame.pack(fill=tk.X, padx=20, pady=5)

        # Чувствительность движения
        tk.Frame(settings_win, height=2, bg="gray").pack(fill=tk.X, padx=20, pady=10)
        tk.Label(settings_win, text="Чувствительность движения:", anchor="w").pack(fill=tk.X, padx=20)
        sens_value_label = tk.Label(settings_win, text=f"Текущее значение: {sens_var.get()}")
        sens_value_label.pack(pady=(0, 5))
        settings_win.sens_value_label = sens_value_label

        sens_scale = tk.Scale(
            settings_win,
            from_=50,
            to=5000,
            orient=tk.HORIZONTAL,
            variable=sens_var,
            length=400,
            resolution=10,
            command=lambda val: sens_value_label.config(text=f"Текущее значение: {val}")
        )
        sens_scale.pack(pady=5)

        # Кнопки
        btn_frame = tk.Frame(settings_win)
        btn_frame.pack(pady=15)
        tk.Button(
            btn_frame, text="Сохранить",
            command=lambda: self.apply_settings(
                settings_win, secret_path_var.get(), mode_var.get(), url_var.get(),
                ip_var.get(), port_var.get(), user_var.get(), pass_var.get(),
                stream_path_var.get(), sens_var.get()
            ),
            width=10
        ).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Отмена", command=settings_win.destroy, width=10).pack(side=tk.LEFT, padx=5)

    def apply_settings(self, window, secret_path, mode, url, ip, port, username, password, stream_path, sensitivity):
        try:
            if mode == 'params':
                if not port.isdigit():
                    raise ValueError("Порт должен быть числом")
                if not ip.strip():
                    raise ValueError("IP-адрес не может быть пустым")
                ipaddress.ip_address(ip.strip())
                if not stream_path.startswith('/'):
                    raise ValueError("Путь потока должен начинаться с '/'")
            else:
                u = url.strip()
                if u not in ('0', '1') and not (u.startswith('http://') or u.startswith('https://') or u.startswith('rtsp://')):
                    raise ValueError("URL должен начинаться с http://, https:// или rtsp://")

            self.secret_settings_path = secret_path
            self.connection_mode = mode
            self.camera_url = url
            self.ip = ip
            self.port = port
            self.username = username
            self.password = password
            self.stream_path = stream_path
            self.motion_sensitivity = sensitivity

            self.save_secret_settings()
            self.save_main_settings()

            self.status_label.config(text=f"Настройки: {self.secret_settings_path}", fg="green")
            self.message_queue.put(("info", "Настройки успешно сохранены!"))
            window.destroy()
        except Exception as e:
            self.message_queue.put(("error", f"Ошибка в настройках:\n{e}"))

    def open_detection_window(self):
        if self.last_frame is None:
            messagebox.showwarning("Предупреждение", "Нет доступного кадра для настройки зон детекции.")
            return

        detection_win = Toplevel(self.root)
        detection_win.title("Зоны игнорирования движения")
        detection_win.geometry("800x600")
        detection_win.transient(self.root)
        detection_win.grab_set()

        # Получаем оригинальные размеры кадра
        orig_h, orig_w = self.last_frame.shape[:2]

        # Фрейм и канвас
        canvas_frame = tk.Frame(detection_win)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        canvas = tk.Canvas(canvas_frame, bg="black", highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)

        # Переменные масштабирования
        scale = 1.0
        offset_x = 0
        offset_y = 0
        canvas_img = None
        displayed_rects = []  # для отображения уже сохранённых зон

        def redraw_canvas():
            nonlocal canvas_img, scale, offset_x, offset_y, displayed_rects

            # Очищаем канвас
            canvas.delete("all")
            displayed_rects.clear()

            # Размеры канваса
            cw = canvas.winfo_width()
            ch = canvas.winfo_height()
            if cw <= 1 or ch <= 1:
                return

            # Вычисляем масштаб с сохранением пропорций
            scale_w = cw / orig_w
            scale_h = ch / orig_h
            scale = min(scale_w, scale_h)
            new_w = int(orig_w * scale)
            new_h = int(orig_h * scale)

            offset_x = (cw - new_w) // 2
            offset_y = (ch - new_h) // 2

            # Преобразуем кадр в PIL и масштабируем
            frame_rgb = cv2.cvtColor(self.last_frame, cv2.COLOR_BGR2RGB)
            img_pil = Image.fromarray(frame_rgb)
            img_resized = img_pil.resize((new_w, new_h), Image.Resampling.LANCZOS)
            canvas_img = ImageTk.PhotoImage(img_resized)
            canvas.create_image(offset_x, offset_y, anchor=tk.NW, image=canvas_img)

            # Отображаем уже сохранённые зоны
            for (x1, y1, x2, y2) in self.ignore_mask_rects:
                sx1 = offset_x + x1 * scale
                sy1 = offset_y + y1 * scale
                sx2 = offset_x + x2 * scale
                sy2 = offset_y + y2 * scale
                rect_id = canvas.create_rectangle(sx1, sy1, sx2, sy2, outline='yellow', width=2, stipple='gray50')
                displayed_rects.append(rect_id)

        # Изначальная отрисовка
        detection_win.update_idletasks()  # чтобы получить актуальные размеры
        redraw_canvas()

        # Рисование новой зоны
        rect_id = None
        start_x = start_y = 0

        def canvas_to_frame_coords(cx, cy):
            """Преобразует координаты канваса → координаты оригинального кадра."""
            fx = max(0, min(orig_w - 1, int((cx - offset_x) / scale)))
            fy = max(0, min(orig_h - 1, int((cy - offset_y) / scale)))
            return fx, fy

        def on_button_press(event):
            nonlocal start_x, start_y, rect_id
            start_x, start_y = event.x, event.y
            if rect_id:
                canvas.delete(rect_id)
            rect_id = canvas.create_rectangle(start_x, start_y, start_x, start_y, outline='red', width=2)

        def on_mouse_move(event):
            nonlocal rect_id
            if rect_id:
                canvas.coords(rect_id, start_x, start_y, event.x, event.y)

        def on_button_release(event):
            nonlocal rect_id
            if rect_id:
                x1_canvas, y1_canvas = start_x, start_y
                x2_canvas, y2_canvas = event.x, event.y

                # Преобразуем в координаты кадра
                fx1, fy1 = canvas_to_frame_coords(x1_canvas, y1_canvas)
                fx2, fy2 = canvas_to_frame_coords(x2_canvas, y2_canvas)

                # Нормализуем
                fx1, fx2 = sorted([fx1, fx2])
                fy1, fy2 = sorted([fy1, fy2])

                # Игнорируем слишком маленькие зоны
                if fx2 - fx1 < 5 or fy2 - fy1 < 5:
                    canvas.delete(rect_id)
                    rect_id = None
                    return

                self.ignore_mask_rects.append((fx1, fy1, fx2, fy2))
                redraw_canvas()  # перерисовываем всё, включая новую зону
                rect_id = None

        canvas.bind("<ButtonPress-1>", on_button_press)
        canvas.bind("<B1-Motion>", on_mouse_move)
        canvas.bind("<ButtonRelease-1>", on_button_release)

        # Кнопки управления
        control_frame = tk.Frame(detection_win)
        control_frame.pack(pady=10)

        def clear_all():
            self.ignore_mask_rects.clear()
            redraw_canvas()

        def apply_and_close():
            self.save_secret_settings()
            detection_win.destroy()

        tk.Button(control_frame, text="Очистить всё", command=clear_all).pack(side=tk.LEFT, padx=5)
        tk.Button(control_frame, text="Применить", command=apply_and_close, bg="lightgreen").pack(side=tk.LEFT, padx=5)
        tk.Button(control_frame, text="Отмена", command=detection_win.destroy).pack(side=tk.LEFT, padx=5)

        tk.Label(detection_win, text="Нарисуйте прямоугольники — в них движение игнорируется", fg="blue").pack(pady=(5, 0))

        # Обновляем при изменении размера окна
        def on_resize(event):
            if event.widget == detection_win:
                detection_win.after(50, redraw_canvas)

        detection_win.bind("<Configure>", on_resize)

    def open_sound_settings(self):
        sound_win = Toplevel(self.root)
        sound_win.title("Настройка звука")
        sound_win.geometry("400x150")
        sound_win.transient(self.root)
        sound_win.grab_set()

        tk.Label(sound_win, text="Звук при детекции движения:", anchor="w").pack(fill=tk.X, padx=20, pady=(10,5))

        sound_path_var = tk.StringVar(value=self.sound_file)
        entry = tk.Entry(sound_win, textvariable=sound_path_var, state='readonly')
        entry.pack(fill=tk.X, padx=20, pady=5)

        def choose_sound():
            path = filedialog.askopenfilename(
                title="Выберите звуковой файл (.wav)",
                filetypes=[("WAV files", "*.wav"), ("All files", "*.*")]
            )
            if path:
                sound_path_var.set(path)
                self.sound_file = path

        tk.Button(sound_win, text="Обзор...", command=choose_sound).pack(pady=5)

        def save_sound():
            self.sound_file = sound_path_var.get()
            self.save_secret_settings()
            sound_win.destroy()
            self.message_queue.put(("info", "Звук настроен!"))

        btn_frame = tk.Frame(sound_win)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Сохранить", command=save_sound, width=10).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Отмена", command=sound_win.destroy, width=10).pack(side=tk.LEFT, padx=5)

    def show_info(self):
        info_text = (
            f"Программа Nexora {APP_VERSION}\n"
            f"Автор: {AUTHOR}\n\n"
            "Основные функции:\n"
            "• Поддержка подключения к IP-камерам по RTSP/HTTP или к встроенной веб-камере.\n"
            "• Обнаружение движения на основе анализа изменений в кадре.\n"
            "• Настройка чувствительности детектора движения.\n"
            "• Возможность задать зоны игнорирования движения.\n"
            "• Воспроизведение звука при срабатывании.\n"
            "• Сохранение и загрузка конфигураций подключения в файл.\n"
            "• Отображение статуса подключения и журнала событий.\n"
            "• Простой и интуитивно понятный интерфейс.\n\n"
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
        self.status_label.config(text=f"Настройки: {self.secret_settings_path}", fg="blue")
        self.message_queue.put(("log", "Видеопоток остановлен"))

    def show_motion_alert(self):
        # Закрываем предыдущее окно, если оно открыто
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

        # Воспроизведение звука
        if self.sound_file and os.path.exists(self.sound_file):
            try:
                winsound.PlaySound(self.sound_file, winsound.SND_FILENAME | winsound.SND_ASYNC)
            except Exception as e:
                self.message_queue.put(("log", f"Не удалось воспроизвести звук: {e}"))

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

                    # Получаем bounding box контура
                    x, y, w, h = cv2.boundingRect(contour)
                    cx, cy = x + w // 2, y + h // 2  # центр контура

                    # Проверяем, попадает ли центр в зону игнорирования
                    in_ignored_zone = False
                    for (x1, y1, x2, y2) in self.ignore_mask_rects:
                        if x1 <= cx <= x2 and y1 <= cy <= y2:
                            in_ignored_zone = True
                            break

                    if not in_ignored_zone:
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

                status_text = "ДЕТЕКЦИЯ ДВИЖЕНИЯ!" if motion_detected else "Спокойно"
                color = (255, 0, 0) if motion_detected else (0, 255, 0)

                draw = ImageDraw.Draw(img_pil)
                try:
                    font = ImageFont.truetype("arialbd.ttf", 36)
                except:
                    try:
                        font = ImageFont.truetype("arial.ttf", 32)
                    except:
                        font = ImageFont.load_default()

                # Подложка для текста
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