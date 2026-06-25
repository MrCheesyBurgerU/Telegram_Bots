# Servidor casero en Android: Termux + Ubuntu + Bot de Telegram

Guía paso a paso para convertir un teléfono Android (probado en Samsung Galaxy
S21 FE) en un pequeño servidor Linux accesible por SSH, con una distro Ubuntu
corriendo dentro, y un bot de Telegram que recuerda la toma de medicamentos.

La estructura por capas es importante de entender desde el inicio:

```
Android (el teléfono)
 └─ Termux (la app de terminal)
     └─ proot-distro → Ubuntu (la distro Linux)
         └─ pillbot.py (el bot de Telegram)
```

SSH te deja en **Termux**. Para llegar al bot tienes que entrar a **Ubuntu**.
Tenlo presente en toda la guía: cada comando indica en qué capa se ejecuta.

---

## 1. Instalar Termux y Termux:Boot

Instala ambas apps desde **F-Droid** o **GitHub**, NO desde Play Store (esa
versión está obsoleta). Ambas deben venir de la misma fuente para que las
firmas coincidan.

- **Termux**: la terminal.
- **Termux:Boot**: permite que scripts se ejecuten al encender el teléfono.

Abre **Termux:Boot una vez** después de instalarla, para que Android le conceda
el permiso de autoarranque. No hace falta que haga nada más.

---

## 2. Preparar Termux

Abre Termux y actualiza los paquetes:

```bash
pkg update && pkg upgrade -y
```

Da acceso al almacenamiento (opcional pero útil):

```bash
termux-setup-storage
```

---

## 3. Configurar SSH

Esto permite administrar el teléfono desde tu PC con un teclado de verdad.

Instala OpenSSH:

```bash
pkg install openssh -y
```

Define una contraseña para tu usuario (no se ve mientras escribes):

```bash
passwd
```

Averigua tu usuario y tu IP local:

```bash
whoami          # ej: u0_a326
ip addr show wlan0   # busca la linea "inet", ej: 192.168.1.144
```

Arranca el servidor SSH (Termux usa el puerto **8022**, no el 22):

```bash
sshd
```

Desde tu PC, en la misma red wifi, conéctate:

```bash
ssh -p 8022 u0_a326@192.168.1.144
```

> Consejo: asigna una **reserva DHCP** en tu router a la MAC del teléfono para
> que la IP no cambie.

---

## 4. Mantener el teléfono despierto (CRÍTICO)

Android suspende las apps en segundo plano de forma agresiva, especialmente en
Samsung/One UI. Sin esto, los procesos se mueren (sobre todo de noche).

En **Termux**, activa el wake lock:

```bash
termux-wake-lock
```

En **Android**, además:

- Ajustes → Aplicaciones → Termux → Batería → **Sin restricciones**.
- Lo mismo para **Termux:Boot**.
- Quita ambas de cualquier lista de "apps en suspensión".

Sin estos ajustes, ningún truco de software mantiene los procesos vivos.

---

## 5. Instalar Ubuntu con proot-distro

En **Termux**:

```bash
pkg install proot-distro -y
proot-distro install ubuntu
```

Para entrar a la distro:

```bash
proot-distro login ubuntu
```

El prompt cambia a algo como `root@localhost:~#`. Eso indica que estás **dentro
de Ubuntu**. Para salir y volver a Termux: `exit`.

---

## 6. Configurar Ubuntu

Todo lo de esta sección se ejecuta **dentro de Ubuntu**.

### Zona horaria (IMPORTANTE)

Una distro recién instalada suele venir en UTC. Si el bot dispara recordatorios
por hora, esto debe estar correcto o las horas saldrán mal.

Verifica la hora actual:

```bash
date
```

Si no coincide con tu hora local, ajusta la zona horaria (ejemplo para CDMX):

```bash
ln -sf /usr/share/zoneinfo/America/Mexico_City /etc/localtime
```

Vuelve a verificar con `date` que ya muestre la hora correcta.

### Python y dependencias

```bash
apt update
apt install -y python3 python3-pip python3-requests
```

> Usamos `apt install python3-requests` y NO `pip install requests`, porque las
> versiones recientes de Ubuntu bloquean pip a nivel de sistema (error
> `externally-managed-environment`).

Verifica:

```bash
python3 --version
python3 -c "import requests; print('requests OK')"
```

---

## 7. Crear el bot en Telegram

Esto se hace desde **tu Telegram** (en tu teléfono personal), hablando con
**@BotFather**.

1. Escribe a @BotFather y envía `/newbot`.
2. Dale un nombre (ej: "Recordatorio de Medicinas").
3. Dale un username terminado en `bot` (ej: `recordatorio_papa_bot`).
4. Copia el **TOKEN** que te entrega.

La persona que recibirá los recordatorios debe **iniciar el bot**: le pasas el
enlace `https://t.me/EL_USERNAME_DEL_BOT` y toca "Iniciar".

### Obtener el CHAT ID

Con el token, y después de que la persona le haya escrito al bot, ejecuta
(dentro de Ubuntu):

```bash
curl -s "https://api.telegram.org/bot<TU_TOKEN>/getUpdates" | python3 -m json.tool
```

Busca `"chat":{"id":123456789,...}`. Ese número es el CHAT ID.

> Si sale vacío: la persona no le ha escrito al bot todavía, o el bot ya estaba
> corriendo y consumió el mensaje. Detén el bot, que la persona reenvíe un
> mensaje, y reintenta.

---

## 8. Estructura del proyecto y credenciales

Crea la estructura de carpetas (dentro de Ubuntu):

```bash
mkdir -p /home/pillbot/src /home/pillbot/data /home/pillbot/logs
```

- `src/`  → el código (`pillbot.py`) y el `.env`
- `data/` → el historial de tomas (CSV)
- `logs/` → los registros de actividad

Coloca `pillbot.py` dentro de `src/`. Luego crea el archivo de credenciales:

```bash
nano /home/pillbot/src/.env
```

Contenido del `.env`:

```
TELEGRAM_TOKEN=tu_token_de_botfather
TELEGRAM_CHAT_ID=el_chat_id
```

Guarda con `Ctrl+O`, `Enter`, y sal con `Ctrl+X`.

> El bot lee estas credenciales del `.env`, así no quedan escritas en el código.
> Si subes el proyecto a Git, agrega `.env` a tu `.gitignore`.

---

## 9. Probar el bot

Antes de dejarlo fijo, conviene ver un recordatorio llegar de verdad. Edita el
`SCHEDULE` dentro de `pillbot.py` y agrega temporalmente una toma un par de
minutos en el futuro (mira la hora con `date`):

```python
{"hour": 16, "minute": 12, "meds": ["PRUEBA"], "days": None},
```

Lánzalo (dentro de Ubuntu):

```bash
cd /home/pillbot
python3 src/pillbot.py
```

Verás los logs de arranque y el horario cargado. A la hora puesta debe llegar el
mensaje a Telegram con el botón "Ya las tomé". Tócalo y verifica que:

- Llega el mensaje de confirmación.
- Se registró la toma:

```bash
cat /home/pillbot/data/medication_history.csv
```

Si todo va bien, quita la línea de prueba.

---

## 10. Dejar el bot corriendo con tmux

`tmux` crea una sesión de terminal que sobrevive al cierre de SSH.

En **Termux** (no en Ubuntu):

```bash
termux-wake-lock          # asegura el wake lock
pkg install tmux -y       # si no esta instalado
tmux new -s bot           # crea la sesion "bot"
```

Ya dentro de tmux, entra a Ubuntu y lanza:

```bash
proot-distro login ubuntu
cd /home/pillbot
python3 src/pillbot.py
```

Desconéctate de tmux SIN cerrarlo: pulsa `Ctrl+b`, suelta, y luego `d`.
Ahora puedes cerrar SSH y el bot sigue corriendo.

Comandos útiles de tmux:

```bash
tmux ls                   # ver sesiones activas
tmux attach -t bot        # volver a la sesion (ver logs en vivo)
tmux kill-session -t bot  # detener la sesion (y el bot)
```

Detener el bot manualmente (dentro de Ubuntu):

```bash
pkill -f pillbot.py
```

---

## 11. Arranque automático al encender el teléfono

Para que todo levante solo tras reiniciar, se usa el script de Termux:Boot.

En **Termux**:

```bash
mkdir -p ~/.termux/boot
nano ~/.termux/boot/start-server.sh
```

Contenido:

```bash
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
sshd
proot-distro login ubuntu -- bash -c "cd /home/pillbot && nohup python3 src/pillbot.py >> logs/nohup.log 2>&1 &"
```

Dale permiso de ejecución:

```bash
chmod +x ~/.termux/boot/start-server.sh
```

El `nohup ... &` al final es necesario para que el script no se quede bloqueado
esperando a que el bot termine (nunca termina).

### Probar el arranque automático

1. Reinicia el teléfono.
2. Espera ~1-2 minutos sin abrir nada.
3. Conéctate por SSH y verifica:

```bash
proot-distro login ubuntu
ps aux | grep pillbot      # debe aparecer "python3 src/pillbot.py"
tail /home/pillbot/logs/pillbot.log
```

---

## Comandos de diagnóstico rápido

| Para... | Comando | Capa |
|---|---|---|
| Saber en qué capa estás | mira el prompt (`~ $` = Termux, `root@localhost` = Ubuntu) | — |
| Ver si el bot corre | `ps aux \| grep pillbot` | Ubuntu |
| Ver actividad del bot | `tail -f /home/pillbot/logs/pillbot.log` | Ubuntu |
| Ver el historial de tomas | `cat /home/pillbot/data/medication_history.csv` | Ubuntu |
| Ver la hora del sistema | `date` | Ubuntu |
| Detener el bot | `pkill -f pillbot.py` | Ubuntu |
| Ver sesiones tmux | `tmux ls` | Termux |

---

## Notas importantes

- **Esto es una ayuda, no un sistema médico crítico.** El teléfono puede
  reiniciarse, quedarse sin batería o perder internet. Mantén un respaldo (por
  ejemplo, un pastillero semanal físico).
- **El wake lock y los ajustes de batería son la causa #1 de fallos.** Si el bot
  "se muere solo", casi siempre es esto.
- **Verifica la zona horaria** cada vez que reinstales la distro.
- **Cuida la batería:** tener el teléfono enchufado 24/7 genera calor y la
  degrada. Si tu Samsung lo permite, activa "Proteger batería" para limitar la
  carga al 85%.