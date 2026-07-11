# Mosquiteros Brezza - despliegue publico

Esta carpeta contiene la app lista para publicarse como servicio web Python.

## Opcion recomendada: Render

1. Crea una cuenta en Render.
2. Sube esta carpeta a un repositorio de GitHub.
3. En Render selecciona New > Blueprint o New > Web Service.
4. Si usas Blueprint, Render detecta `render.yaml`.
5. Si usas Web Service manual:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python server.py`
   - Environment: Python
6. Configura estas variables:
   - `APP_USER`: `brezza`
   - `APP_PASSWORD`: la contrasena que quieras usar

Cuando termine el deploy, Render entrega un link publico tipo:

`https://mosquiteros-brezza.onrender.com`

## Nota importante

La app procesa PDFs. No publiques el link sin contrasena si van a subir HTF reales.
