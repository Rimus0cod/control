# Telegram PC Control Bot

Кроссплатформенный Telegram бот для удалённого управления ПК с поддержкой Windows и Linux.

## 🚀 Возможности

### Управление ПК
- **Статус системы** - CPU, RAM, диск, uptime, батарея
- **Скриншот** - сделать скриншот рабочего стола
- **Перезагрузка** - перезагрузить ПК
- **Выключение** - выключить ПК
- **Спящий режим** - перевести ПК в спящий режим
- **Гибернация** - перевести ПК в режим гибернации
- **Процессы** - список запущенных процессов
- **Завершить процесс** - завершить процесс по PID или имени
- **Сбор данных** - комплексная информация о системе
- **Сеть** - активные сетевые соединения
- **Выполнить команду** - выполнить shell-команду

### Безопасность
- Авторизация по паролю
- 2FA (TOTP) поддержка
- Защита от брутфорса (5 попыток, блокировка на 5 минут)
- Логирование всех действий
- Подтверждение опасных действий

### Дополнительно
- Многопользовательская поддержка
- Уведомления о событиях
- Интеграция с Dota 2 (опционально)
- Wake-on-LAN

## 📋 Требования

- Python 3.10+
- Telegram Bot Token

## 🛠 Установка

### 1. Клонирование репозитория

```bash
git clone https://github.com/Rimus0cod/control.git
cd control
```

### 2. Установка зависимостей

**Windows:**
```powershell
pip install -r requirements.txt
```

**Linux:**
```bash
pip install -r requirements.txt
```

### 3. Настройка переменных окружения

Создайте файл `.env` на основе примера:

```env
# Токен бота (получить у @BotFather)
BOT_TOKEN=your_bot_token_here

# ID администраторов (через запятую)
ADMIN_IDS=123456789,987654321

# База данных
DATABASE_URL=sqlite+aiosqlite:///bot.db

# IP адрес ПК (для Wake-on-LAN)
PC_IP_ADDRESS=192.168.1.100
PC_MAC_ADDRESS=xx:xx:xx:xx:xx:xx

# Настройки логирования
LOG_LEVEL=INFO
LOG_FILE=bot.log
```

## 🖥 Запуск бота

### Windows
```powershell
python bot/main.py
```

### Linux
```bash
python bot/main.py
```

или

```bash
python3 bot/main.py
```

## 🔧 Автозапуск

### Windows (Task Scheduler)

1. Откройте "Планировщик заданий" (Task Scheduler)
2. Создайте новую задачу
3. Настройте запуск при входе в систему
4. Укажите путь к Python и скрипту

### Linux (systemd)

Создайте файл `/etc/systemd/system/telegram-pc-bot.service`:

```ini
[Unit]
Description=Telegram PC Control Bot
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/path/to/control
ExecStart=/usr/bin/python3 /path/to/control/bot/main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Затем:
```bash
sudo systemctl daemon-reload
sudo systemctl enable telegram-pc-bot
sudo systemctl start telegram-pc-bot
```

## 📱 Команды бота

### Основные команды
| Команда | Описание |
|---------|----------|
| `/start` | Запуск бота |
| `/help` | Справка |
| `/status` | Статус ПК |
| `/screenshot` | Скриншот |
| `/reboot` | Перезагрузка |
| `/shutdown` | Выключение |
| `/sleep` | Спящий режим |
| `/hibernate` | Гибернация |
| `/cancel` | Отменить выключение |
| `/processes` | Топ процессов |
| `/list_processes` | Все процессы |
| `/kill_process` | Завершить процесс |
| `/collect_data` | Сбор данных ПК |
| `/network` | Сетевые соединения |
| `/cmd <команда>` | Выполнить команду |

### Админ команды
| Команда | Описание |
|---------|----------|
| `/login <пароль>` | Авторизация |
| `/register` | Регистрация |
| `/2fa` | Настройка 2FA |
| `/admin` | Панель админа |

## 🔐 Настройка безопасности

### Установка пароля администратора

```python
# В боте выполните (будучи админом):
/setpassword your_secure_password
```

### Настройка 2FA

```python
# В боте:
/2fa

# Следуйте инструкциям для сканирования QR-кода
```

## 🖥 Скриншоты

### Linux
Для работы скриншотов установите:
```bash
# Arch Linux
pacman -S scrot

# Ubuntu/Debian
apt install scrot

# Fedora
dnf install scrot
```

Альтернативно, бот может использовать:
- `import` (ImageMagick)
- `gnome-screenshot`
- `spectacle` (KDE)

### Windows
Скриншоты работают автоматически через библиотеку `mss` или `Pillow`.

## 📂 Структура проекта

```
control/
├── bot/                    # Основной код бота
│   ├── main.py            # Точка входа
│   ├── keyboards.py       # Клавиатуры
│   └── filters.py        # Фильтры
├── handlers/              # Обработчики команд
│   ├── pc_control.py     # Управление ПК
│   ├── authorization.py  # Авторизация
│   └── admin.py          # Админ-панель
├── services/             # Сервисы
│   ├── pc_manager.py     # Управление ПК
│   ├── two_factor.py     # 2FA
│   └── notifications.py  # Уведомления
├── database/              # База данных
│   ├── models.py         # Модели SQLAlchemy
│   └── repository.py    # Репозиторий
├── config/               # Конфигурация
│   └── settings.py       # Настройки
└── utils/                # Утилиты
    ├── logger.py         # Логирование
    └── validators.py    # Валидаторы
```

## 🐛 Устранение проблем

### Бот не запускается
1. Проверьте токен бота в `.env`
2. Убедитесь, что установлены все зависимости
3. Проверьте логи в `bot.log`

### Скриншоты не работают (Linux)
```bash
# Установите scrot
sudo apt install scrot

# Или ImageMagick
sudo apt install imagemagick
```

### Команды выключения не работают
- Linux: запустите бота с правами `sudo`
- Windows: запустите от имени администратора

### Нет доступа к базе данных
```bash
# Права на файл базы данных
chmod 666 bot.db
```

## 📄 Лицензия

MIT License

## 🤝 Вклад в проект

Pull requests приветствуются!
