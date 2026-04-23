# 🚀 Guía para conectarse a la base de datos (SAP HANA Cloud)

## 🧑‍💻 1. Entrar a SAP

1. Ir a: https://account.hanatrial.ondemand.com
2. Iniciar sesión con tu cuenta SAP

---

## 🧭 2. Entrar al proyecto

1. Click en **"Go To Your Trial Account"**
2. Click en **"trial"** (subaccount)

---

## 🗄️ 3. Abrir la base de datos

1. En el menú izquierdo, ir a:
   👉 **SAP HANA Cloud**
2. Luego abrir:
   👉 **SAP HANA Database Explorer**

---

## ➕ 4. Conectar a la base de datos

1. Click en: **"Add Database"**
2. Seleccionar: **SAP HANA Database**

---

## ✍️ 5. Llenar los datos

Usar estos datos:

* **Host:**
  `ab4ecef0-0086-4162-aee8-14b8d3c23569.hna1.prod-us10.hanacloud.ondemand.com`

* **Port:**
  `443`

* **User:**
  `DBADMIN`

* **Password:**
  (preguntar a Leo)

---

## 🔌 6. Conectar

👉 Click en **Connect**

---

## ✅ 7. Listo

Si todo sale bien, ya puedes:

* Ver tablas
* Crear tablas
* Ejecutar queries SQL

---

## ⚠️ Errores comunes

* ❌ Poner mal el password
* ❌ Usar otro usuario (no es el nombre de la DB)
* ❌ No poner el puerto 443
* ❌ Copiar mal el host

---

## 💬 Si no te deja entrar

Avísame y lo vemos en 2 min 👍

---

## 🔧 Configuración Backend Python

Si conectas desde la aplicación backend, usa estas variables de entorno en `.env`:

```bash
STORAGE_BACKEND=hana
HANA_HOST=ab4ecef0-0086-4162-aee8-14b8d3c23569.hna1.prod-us10.hanacloud.ondemand.com
HANA_PORT=443
HANA_USER=DBADMIN
HANA_PASSWORD=<password-de-leo>
HANA_SCHEMA=SOC_PIPELINE
```

Luego instala el driver:

```bash
python -m pip install -r requirements-hana.txt
```

Y levanta el backend con:

```bash
python main.py
```

Las tablas (`RAW_LOGS`, `INGEST_RUNS`, `ALERTS_EVENTS`) se crean automáticamente en el primer startup.
