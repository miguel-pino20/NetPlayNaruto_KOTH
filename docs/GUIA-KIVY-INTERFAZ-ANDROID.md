# Guía básica de Kivy para la interfaz móvil de Netplay

Empieza con un cambio visual pequeño en **Ayuda**. Después organiza el menú. Puedes practicar ambas cosas desde Linux y dejar para el teléfono la revisión del tamaño real, el teclado y el botón Atrás.

## Dónde empezar en el proyecto

La interfaz está construida en Python. `build()` arma la ventana y reúne las pestañas. `page()` crea una pestaña con contenido desplazable. `button()` crea botones y `set_text()` registra textos traducibles. Para agregar un control, busca primero un ejemplo que ya use esos métodos. [Interfaz móvil](../mobile/main.py#L42) · [Métodos para construir pantallas](../mobile/main.py#L229)

Abre la app con las instrucciones de **Ejecutar la interfaz en Linux**. Si ya tienes preparado el entorno móvil, desde la raíz del repositorio basta con ejecutar `mobile/.venv/bin/python mobile/main.py`. Esta vista sirve para revisar el diseño y la navegación. P1, P2 y ARMSX2 se prueban en Android. [Guía de ejecución del proyecto](../mobile/README.md#ejecutar-la-interfaz-en-linux)

## Conceptos que vas a usar

| Concepto | Para qué sirve aquí |
|---|---|
| **Widget** | `Label` muestra texto, `Button` ejecuta una acción y `Spinner` permite elegir una opción. Practica con un botón que cambie un texto al soltarlo, usando `on_release`. [Eventos de Kivy](https://kivy.org/doc/stable/guide/events.html) |
| **BoxLayout** | Ordena controles en una fila o columna. En una pantalla de formulario, usa una columna con `padding` para el margen interior y `spacing` para la distancia entre controles. [BoxLayout](https://kivy.org/doc/stable/api-kivy.uix.boxlayout.html) |
| **Tamaño** | `size_hint` reparte el espacio disponible. Para fijar la altura de un botón dentro de una columna, su `size_hint_y` puede ser `None` y su altura expresarse con `dp`. Usa `dp` para dimensiones y `sp` para texto. [Unidades de Kivy](https://kivy.org/doc/stable/api-kivy.metrics.html) |
| **ScrollView** | Permite recorrer un formulario largo. Usa un único contenedor hijo y deja que su altura crezca con el contenido. El patrón del proyecto vincula `minimum_height` con `height`. [ScrollView](https://kivy.org/doc/stable/api-kivy.uix.scrollview.html) · [Patrón actual en `page()`](../mobile/main.py#L229) |
| **Navegación** | Las pestañas actuales permiten ensayar el menú con poco cambio. Si luego necesitas una portada y pantallas separadas con regreso, `ScreenManager` permite mostrar una pantalla por nombre. [TabbedPanel](https://kivy.org/doc/stable/api-kivy.uix.tabbedpanel.html) · [ScreenManager](https://kivy.org/doc/stable/api-kivy.uix.screenmanager.html) |

## Ejercicios para avanzar con el menú

- [ ] **1 · Ayuda.** Crea una pestaña de práctica con el título **Ayuda** y un botón **Configurar ARMSX2**. Al tocarlo, muestra un texto breve en la misma pantalla. Comprueba que responde y que el texto se puede leer al estrechar la ventana.
- [ ] **2 · Menú principal.** Organiza cuatro entradas **Jugar**, **Juegos**, **Ayuda** e **Historial**. Empieza con encabezados y botones visibles. Comprueba que puedes entrar y volver sin perderte.
- [ ] **3 · Submenús.** En **Jugar**, coloca **PVP**, **Rey de la Colina** y **Torneos**. En **Juegos**, coloca **Catálogo UN5 / UN6** y **Descargar estados**. En **Ayuda**, agrupa configuración, guías y registros. En **Historial**, deja preparada la vista de peleas para el bloque A7. Usa una columna desplazable para pantallas largas.
- [ ] **4 · Enlazar acciones existentes.** Conecta una sección por vez con sus pantallas actuales. Empieza por el acceso a **Torneos** o por **Descargar estados**. Conserva las selecciones al cambiar de menú y deja visibles **Detener** y **Volver a ARMSX2** cuando corresponda.
- [ ] **5 · Revisar en un teléfono.** Comprueba el menú en vertical con el teclado abierto y cerrado. Revisa que los botones se puedan tocar cómodamente, que el texto largo se ajuste, que se pueda desplazar hasta la última opción y que **Atrás** te devuelva a la pantalla anterior.

Anota una línea al terminar cada ejercicio. Por ejemplo, `Interfaz 1 [x] · Ayuda abre y el botón cambia el texto en Linux · Siguiente 2`. Estos ejercicios desarrollan **A3** del [plan móvil](PLAN-ANDROID-NETPLAY.md). La validación de A3 incluye cambiar de pantalla durante una sesión real y comprobar que se conserva.
