"""Translations for the mobile activity and Android foreground service."""

LANGUAGES = {'es': 'Español', 'en': 'English', 'pt': 'Português (Brasil)'}
_language = 'es'


def set_language(code):
    global _language
    _language = code if isinstance(code, str) and code in LANGUAGES else 'es'
    return _language


def tr(message, **values):
    translations = TRANSLATIONS.get(message)
    if translations and _language != 'es':
        message = translations[0 if _language == 'en' else 1]
    return message.format(**values) if values else message


# Spanish source text maps to English and Brazilian Portuguese.
TRANSLATIONS = {
    'Inscripción a torneos': ('Tournament registration', 'Inscrições em torneios'),
    'No hay torneos con inscripción abierta.': ('No tournaments open for registration.', 'Nenhum torneio com inscrições abertas.'),
    'Inscribirme en {event}': ('Register for {event}', 'Inscrever-se em {event}'),
    'Inicia sesión con Discord para inscribirte.': ('Sign in with Discord to register.', 'Entre com Discord para se inscrever.'),
    'Inscripción confirmada en {name} (#{id}).': ('Registered for {name} (#{id}).', 'Inscrição confirmada em {name} (#{id}).'),
    'Cancelar': ('Cancel', 'Cancelar'),
    'Crear evento casual': ('Create casual event', 'Criar evento casual'),
    'Iniciar evento casual': ('Start casual event', 'Iniciar evento casual'),
    'Nombre del evento': ('Event name', 'Nome do evento'),
    'Puntos para ganar (1–1000)': ('Points to win (1–1000)', 'Pontos para vencer (1–1000)'),
    'Cupo de jugadores (2–100)': ('Player limit (2–100)', 'Limite de jogadores (2–100)'),
    'Revisa el nombre, la meta y el cupo.': ('Check the name, target and player limit.', 'Confira o nome, a meta e o limite de jogadores.'),
    'Evento creado: {event}.': ('Event created: {event}.', 'Evento criado: {event}.'),
    'Evento iniciado: {event}.': ('Event started: {event}.', 'Evento iniciado: {event}.'),

    'Idioma': (
        'Language',
        'Idioma',
    ),
    'Base Android · PINE / ZeroTier / KOTH': (
        'Android · PINE / ZeroTier / KOTH',
        'Android · PINE / ZeroTier / KOTH',
    ),
    'Conexión': (
        'Connection',
        'Conexão',
    ),
    'Versión {version}': (
        'Version {version}',
        'Versão {version}',
    ),
    'Actualizaciones de GitHub': (
        'GitHub updates',
        'Atualizações do GitHub',
    ),
    'Buscar actualizaciones': (
        'Check for updates',
        'Buscar atualizações',
    ),
    'Descargar actualización': (
        'Download update',
        'Baixar atualização',
    ),
    'Instalar actualización': (
        'Install update',
        'Instalar atualização',
    ),
    'Puerto PINE': (
        'PINE port',
        'Porta PINE',
    ),
    'Probar PINE (solo lectura)': (
        'Test PINE (read-only)',
        'Testar PINE (somente leitura)',
    ),
    'Estado compartido para ARMSX2': (
        'Shared save state for ARMSX2',
        'Estado salvo compartilhado para ARMSX2',
    ),
    'Descargar estado en Descargas': (
        'Save state to Downloads',
        'Salvar estado em Downloads',
    ),
    'Se guarda en Descargas/NarutoNetplay. Debes pasarlo a ARMSX2 por tu cuenta.': (
        'Saved to Downloads/NarutoNetplay. Transfer it to ARMSX2 manually.',
        'Salvo em Downloads/NarutoNetplay. Transfira o arquivo manualmente para o ARMSX2.',
    ),
    'Tu IPv4 de ZeroTier': (
        'Your ZeroTier IPv4',
        'Seu IPv4 do ZeroTier',
    ),
    'Guardar configuración': (
        'Save settings',
        'Salvar configurações',
    ),
    'Conecta y autoriza la red desde ZeroTier.\nEl host experimental se inicia en la pestaña Host P1.': (
        'Join and authorize the network in ZeroTier.\nStart the experimental host from the Host P1 tab.',
        'Conecte-se à rede e autorize-a no ZeroTier.\nInicie o host experimental na aba Host P1.',
    ),
    'Control flotante movible': (
        'Movable floating control',
        'Controle flutuante móvel',
    ),
    'Crear partida como jugador 1': (
        'Host a match as player 1',
        'Criar partida como jogador 1',
    ),
    'Detener partida': (
        'Stop match',
        'Encerrar partida',
    ),
    'Volver a ARMSX2': (
        'Return to ARMSX2',
        'Voltar ao ARMSX2',
    ),
    'Host detenido.': (
        'Host stopped.',
        'Host encerrado.',
    ),
    'El slot 1 de ARMSX2 debe contener el estado compartido preparado.\nLa app descarga una copia privada, pero no puede instalarla en ARMSX2 automáticamente.\nServidor UN5: la sala aparece en PC. Directo/ZeroTier: P2 conecta a tu IP, UDP 47400.': (
        'ARMSX2 slot 1 must contain the prepared shared save state.\nThe app downloads a private copy. Install it in ARMSX2 manually.\nUN5 server: the room appears on PC. Direct/ZeroTier: P2 connects to your IP on UDP 47400.',
        'O slot 1 do ARMSX2 deve conter o estado salvo compartilhado.\nO app baixa uma cópia privada. Instale-a manualmente no ARMSX2.\nServidor UN5: a sala aparece no PC. Direto/ZeroTier: P2 conecta ao seu IP pela porta UDP 47400.',
    ),
    'Cliente P2': (
        'Client P2',
        'Cliente P2',
    ),
    'Servidor UN5': (
        'UN5 server',
        'Servidor UN5',
    ),
    'Directo / ZeroTier': (
        'Direct / ZeroTier',
        'Direto / ZeroTier',
    ),
    'IPv4 del host P1 · puerto 47400': (
        'P1 host IPv4 · port 47400',
        'IPv4 do host P1 · porta 47400',
    ),
    'IP del host': (
        'Host IP',
        'IP do host',
    ),
    'Actualizar salas UN5': (
        'Refresh UN5 rooms',
        'Atualizar salas UN5',
    ),
    'Pulsa Actualizar salas para buscar jugadores.': (
        'Tap Refresh UN5 rooms to find players.',
        'Toque em Atualizar salas UN5 para encontrar jogadores.',
    ),
    'Conectar como jugador 2': (
        'Connect as player 2',
        'Conectar como jogador 2',
    ),
    'Desconectar': (
        'Disconnect',
        'Desconectar',
    ),
    'Sin conexión.': (
        'Disconnected.',
        'Desconectado.',
    ),
    'Usa tus controles locales del mando 1: netplay los asigna al jugador 2. Ambos puertos virtuales se preparan como DualShock 2.': (
        'Use your local controller 1. Netplay assigns it to player 2. Both virtual ports use DualShock 2.',
        'Use o controle local 1. O netplay o atribui ao jogador 2. As duas portas virtuais usam DualShock 2.',
    ),
    'Servidor KOTH (HTTPS)': (
        'KOTH server (HTTPS)',
        'Servidor KOTH (HTTPS)',
    ),
    'Actualizar eventos': (
        'Refresh events',
        'Atualizar eventos',
    ),
    'Pulsa Actualizar eventos para buscar torneos.': (
        'Tap Refresh events to find tournaments.',
        'Toque em Atualizar eventos para encontrar torneios.',
    ),
    'Inscribirme y conectar': (
        'Sign up and connect',
        'Inscrever-se e conectar',
    ),
    'Desconectar de KOTH': (
        'Disconnect from KOTH',
        'Desconectar do KOTH',
    ),
    'KOTH desconectado.': (
        'KOTH disconnected.',
        'KOTH desconectado.',
    ),
    'Sin sesión verificada': (
        'No verified session',
        'Sem sessão verificada',
    ),
    'Iniciar sesión con Discord': (
        'Sign in with Discord',
        'Entrar com Discord',
    ),
    'Cancelar login': (
        'Cancel sign-in',
        'Cancelar login',
    ),
    'Cerrar sesión': (
        'Sign out',
        'Sair',
    ),
    'El login abre el navegador y usa el servidor existente.\nLa sesión se guarda en los datos privados de esta app.\nNunca se incluye el secreto de Discord en el APK.': (
        'Sign-in opens your browser and uses the existing server.\nThe session is stored in this app’s private data.\nThe APK never contains the Discord secret.',
        'O login abre o navegador e usa o servidor existente.\nA sessão fica nos dados privados do app.\nO APK nunca contém o segredo do Discord.',
    ),
    'Listo. Activa PINE en ARMSX2 antes de probar.': (
        'Ready. Enable PINE in ARMSX2 before testing.',
        'Pronto. Ative o PINE no ARMSX2 antes de testar.',
    ),
    'Discord debe abrirse mediante HTTPS.': (
        'Discord must open over HTTPS.',
        'O Discord deve abrir via HTTPS.',
    ),
    'Espera a que termine la consulta actual.': (
        'Wait for the current request to finish.',
        'Aguarde a conclusão da solicitação atual.',
    ),
    'Consultando…': (
        'Working…',
        'Processando…',
    ),
    'Puerto PINE inválido.': (
        'Invalid PINE port.',
        'Porta PINE inválida.',
    ),
    'Configuración guardada. La conectividad ZeroTier aún debe probarse en una partida.': (
        'Settings saved. Test your ZeroTier connection in a match.',
        'Configurações salvas. Teste a conexão ZeroTier em uma partida.',
    ),
    'Buscando actualizaciones…': (
        'Checking for updates…',
        'Buscando atualizações…',
    ),
    'No se pudo comprobar: {error}': (
        'Update check failed: {error}',
        'Falha ao buscar atualizações: {error}',
    ),
    'Consulta de actualizaciones completada.': (
        'Update check complete.',
        'Busca por atualizações concluída.',
    ),
    'Disponible: {version}': (
        'Available: {version}',
        'Disponível: {version}',
    ),
    'No hay una actualización posterior a {version}': (
        'No update newer than {version}',
        'Nenhuma atualização posterior à versão {version}',
    ),
    'Nueva versión {version}. ¿Descargar APK?': (
        'New version {version}. Download the APK?',
        'Nova versão {version}. Baixar o APK?',
    ),
    'Actualización disponible': (
        'Update available',
        'Atualização disponível',
    ),
    'Descargar': (
        'Download',
        'Baixar',
    ),
    'Más tarde': (
        'Later',
        'Mais tarde',
    ),
    'Detén la partida antes de descargar o instalar una actualización.': (
        'Stop the match before downloading or installing an update.',
        'Encerre a partida antes de baixar ou instalar uma atualização.',
    ),
    'Descargando {version} y verificando SHA256…': (
        'Downloading {version} and verifying SHA256…',
        'Baixando {version} e verificando o SHA256…',
    ),
    'No se pudo descargar: {error}': (
        'Download failed: {error}',
        'Falha no download: {error}',
    ),
    'APK {version} verificado. Pulsa Instalar actualización.': (
        'APK {version} verified. Tap Install update.',
        'APK {version} verificado. Toque em Instalar atualização.',
    ),
    'Guardar en Descargas está disponible en Android 10 o posterior.': (
        'Saving to Downloads is available on Android 10 or later.',
        'Salvar em Downloads está disponível no Android 10 ou posterior.',
    ),
    'Descargando y verificando estado {game}…': (
        'Downloading and verifying the {game} save state…',
        'Baixando e verificando o estado salvo de {game}…',
    ),
    'Inicia sesión con Discord para inscribirte y conectar.': (
        'Sign in with Discord to sign up and connect.',
        'Entre com Discord para se inscrever e conectar.',
    ),
    'Actualiza los eventos del servidor KOTH.': (
        'Refresh the events from the KOTH server.',
        'Atualize os eventos do servidor KOTH.',
    ),
    'Selecciona un evento disponible.': (
        'Select an available event.',
        'Selecione um evento disponível.',
    ),
    'Si tu IP de ZeroTier registrada cambia, perderás hasta 1 punto.': (
        'If your registered ZeroTier IP changes, you will lose up to 1 point.',
        'Se o IP do ZeroTier cadastrado mudar, você perderá até 1 ponto.',
    ),
    'No hay eventos disponibles.': (
        'No events available.',
        'Nenhum evento disponível.',
    ),
    'Eventos disponibles: {count}': (
        'Available events: {count}',
        'Eventos disponíveis: {count}',
    ),
    'KOTH requiere tu IPv4 de ZeroTier. Configúrala en la pestaña Conexión.': (
        'KOTH requires your ZeroTier IPv4. Set it in the Connection tab.',
        'O KOTH precisa do seu IPv4 do ZeroTier. Configure-o na aba Conexão.',
    ),
    'Revisa la IPv4 de ZeroTier en la pestaña Conexión.': (
        'Check your ZeroTier IPv4 in the Connection tab.',
        'Confira seu IPv4 do ZeroTier na aba Conexão.',
    ),
    'Ya hay una conexión activa. Desconéctala antes de cambiar de evento o IP.': (
        'A connection is active. Disconnect before changing events or IP addresses.',
        'Já há uma conexão ativa. Desconecte-a antes de mudar de evento ou IP.',
    ),
    'Revisa el puerto PINE en la pestaña Conexión.': (
        'Check the PINE port in the Connection tab.',
        'Confira a porta PINE na aba Conexão.',
    ),
    'Cuenta Discord': (
        'Discord account',
        'Conta do Discord',
    ),
    'No se pudo identificar tu cuenta. Vuelve a iniciar sesión con Discord.': (
        'Could not identify your account. Sign in with Discord again.',
        'Não foi possível identificar sua conta. Entre com Discord novamente.',
    ),
    'Inscripción confirmada en {event}. Puntos: {points}.': (
        'Registration confirmed for {event}. Points: {points}.',
        'Inscrição confirmada em {event}. Pontos: {points}.',
    ),
    'Desconexión de KOTH solicitada.': (
        'KOTH disconnection requested.',
        'Desconexão do KOTH solicitada.',
    ),
    'Hay una operación de cuenta en curso.': (
        'An account operation is already in progress.',
        'Já há uma operação de conta em andamento.',
    ),
    'Completa el login en el navegador. Puedes volver a esta app después.': (
        'Finish signing in in the browser, then return to this app.',
        'Conclua o login no navegador e volte para este app.',
    ),
    'Sesión: {name}': (
        'Signed in as {name}',
        'Sessão: {name}',
    ),
    'Sesión restaurada.': (
        'Session restored.',
        'Sessão restaurada.',
    ),
    'Sesión iniciada.': (
        'Signed in.',
        'Login concluído.',
    ),
    'Sesión cerrada.': (
        'Signed out.',
        'Sessão encerrada.',
    ),
    'Sin actualización reciente: revisa batería y bloqueo de pantalla.': (
        'No recent activity. Check battery and screen lock settings.',
        'Sem atividade recente. Confira as configurações de bateria e de bloqueio de tela.',
    ),
    'El servicio host se inicia desde la APK Android.': (
        'Start the host service from the Android app.',
        'Inicie o serviço de host pelo app Android.',
    ),
    'Permite Mostrar sobre otras apps, vuelve y pulsa Crear partida.': (
        'Allow Display over other apps, return and try again.',
        'Permita a exibição sobre outros apps, volte e tente novamente.',
    ),
    'Ya hay una partida activa. Deténla antes de crear otra.': (
        'Stop the active match before starting another.',
        'Encerre a partida ativa antes de iniciar outra.',
    ),
    'Selecciona una sala de la lista.': (
        'Select a room from the list.',
        'Selecione uma sala na lista.',
    ),
    'Inicia sesión con Discord para entrar al servidor principal.': (
        'Sign in with Discord to join the main server.',
        'Entre com Discord para acessar o servidor principal.',
    ),
    'Servicio iniciando…': (
        'Starting service…',
        'Iniciando serviço…',
    ),
    'Vuelve a ARMSX2 y pulsa Reanudar.': (
        'Return to ARMSX2 and tap Resume.',
        'Volte ao ARMSX2 e toque em Continuar.',
    ),
    'Vuelve a ARMSX2 y pulsa Reanudar. El servicio prepara la partida.': (
        'Return to ARMSX2 and tap Resume. The service prepares the match.',
        'Volte ao ARMSX2 e toque em Continuar. O serviço prepara a partida.',
    ),
    'Parada solicitada. Vuelve a ARMSX2 para liberar el juego.': (
        'Stop requested. Return to ARMSX2 to release the game.',
        'Encerramento solicitado. Volte ao ARMSX2 para liberar o jogo.',
    ),
    'Abre ARMSX2 en el teléfono.': (
        'Open ARMSX2 on your phone.',
        'Abra o ARMSX2 no celular.',
    ),
    'Abre ARMSX2 manualmente y pulsa Reanudar.': (
        'Open ARMSX2 manually and tap Resume.',
        'Abra o ARMSX2 manualmente e toque em Continuar.',
    ),
    'Cancela primero el login y espera a que termine.': (
        'Cancel sign-in and wait for it to finish.',
        'Cancele o login e aguarde a conclusão.',
    ),
    'No hay jugadores esperando en este momento.': (
        'No players are waiting right now.',
        'Nenhum jogador está esperando no momento.',
    ),
    'Salas disponibles: {count}': (
        'Available rooms: {count}',
        'Salas disponíveis: {count}',
    ),
    'Usa una URL HTTPS para proteger tu sesión.': (
        'Use an HTTPS URL to protect your session.',
        'Use uma URL HTTPS para proteger sua sessão.',
    ),
    'Introduce la IPv4 asignada por ZeroTier.': (
        'Enter the IPv4 address assigned by ZeroTier.',
        'Informe o IPv4 atribuído pelo ZeroTier.',
    ),
    'El puerto PINE debe estar entre 1 y 65535.': (
        'The PINE port must be between 1 and 65535.',
        'A porta PINE deve estar entre 1 e 65535.',
    ),
    'PINE responde. Abre Naruto en el emulador para identificar el juego.': (
        'PINE is responding. Open Naruto in the emulator to identify the game.',
        'O PINE está respondendo. Abra Naruto no emulador para identificar o jogo.',
    ),
    'PINE conectado: {endpoint}': (
        'PINE connected: {endpoint}',
        'PINE conectado: {endpoint}',
    ),
    'Estado: {status}': (
        'Status: {status}',
        'Estado: {status}',
    ),
    'en ejecución': (
        'running',
        'em execução',
    ),
    'pausado': (
        'paused',
        'pausado',
    ),
    'Juego: {game}': (
        'Game: {game}',
        'Jogo: {game}',
    ),
    'Emulador: {version}': (
        'Emulator: {version}',
        'Emulador: {version}',
    ),
    'Diagnóstico de solo lectura. No valida todavía NetPad ni la sincronía.': (
        'Read-only diagnostic. NetPad and synchronization still need testing.',
        'Diagnóstico de somente leitura. O NetPad e a sincronização ainda precisam ser testados.',
    ),
    'La actualización no corresponde al APK del repositorio configurado.': (
        'The update does not match the APK from the configured repository.',
        'A atualização não corresponde ao APK do repositório configurado.',
    ),
    'Descarga primero la actualización.': (
        'Download the update first.',
        'Baixe a atualização primeiro.',
    ),
    'Permite instalar desde Naruto Netplay, vuelve y pulsa Instalar actualización.': (
        'Allow installs from Naruto Netplay, return and tap Install update.',
        'Permita instalações pelo Naruto Netplay, volte e toque em Instalar atualização.',
    ),
    'Actualización': (
        'Update',
        'Atualização',
    ),
    'Confirma la actualización en el instalador de Android.': (
        'Confirm the update in the Android installer.',
        'Confirme a atualização no instalador do Android.',
    ),
    'Guardar en Descargas requiere Android 10 o posterior.': (
        'Saving to Downloads requires Android 10 or later.',
        'Salvar em Downloads requer Android 10 ou posterior.',
    ),
    'No se pudo leer el estado compartido.': (
        'Could not read the shared save state.',
        'Não foi possível ler o estado salvo compartilhado.',
    ),
    'Android no permitió guardar el estado en Descargas.': (
        'Android blocked saving the state to Downloads.',
        'O Android impediu que o estado fosse salvo em Downloads.',
    ),
    'No se pudo abrir el destino del estado.': (
        'Could not open the save state destination.',
        'Não foi possível abrir o destino do estado salvo.',
    ),
    'El estado guardado en Descargas no pasó la verificación.': (
        'The save state in Downloads failed verification.',
        'O estado salvo em Downloads falhou na verificação.',
    ),
    'Partida Naruto Netplay': (
        'Naruto Netplay match',
        'Partida Naruto Netplay',
    ),
    'Coordinando turnos con Django': (
        'Coordinating turns with Django',
        'Coordenando turnos com o Django',
    ),
    'Sala UN5 · esperando jugador 2': (
        'UN5 room · waiting for player 2',
        'Sala UN5 · aguardando jogador 2',
    ),
    'Esperando jugador 2 · UDP 47400': (
        'Waiting for player 2 · UDP 47400',
        'Aguardando jogador 2 · UDP 47400',
    ),
    'Sala UN5: {room}': (
        'UN5 room: {room}',
        'Sala UN5: {room}',
    ),
    'HOST P1 · Sala publicada en el servidor UN5. Esperando jugador 2.': (
        'HOST P1 · Room published on the UN5 server. Waiting for player 2.',
        'HOST P1 · Sala publicada no servidor UN5. Aguardando jogador 2.',
    ),
    'CLIENTE P2 · Conectando a P1. Mantén ARMSX2 visible y reanudado.': (
        'CLIENT P2 · Connecting to P1. Keep ARMSX2 visible and running.',
        'CLIENTE P2 · Conectando a P1. Mantenha o ARMSX2 visível e em execução.',
    ),
    'HOST P1 · Esperando jugador 2. Mantén ARMSX2 visible y reanudado.': (
        'HOST P1 · Waiting for player 2. Keep ARMSX2 visible and running.',
        'HOST P1 · Aguardando jogador 2. Mantenha o ARMSX2 visível e em execução.',
    ),
    'HOST P1 · Esperando jugador 2 en UDP 47400. Mantén ARMSX2 visible y reanudado.': (
        'HOST P1 · Waiting for player 2 on UDP 47400. Keep ARMSX2 visible and running.',
        'HOST P1 · Aguardando jogador 2 na porta UDP 47400. Mantenha o ARMSX2 visível e em execução.',
    ),
    'Host P1 iniciando. Vuelve a ARMSX2 y pulsa Reanudar.': (
        'Starting Host P1. Return to ARMSX2 and tap Resume.',
        'Iniciando Host P1. Volte ao ARMSX2 e toque em Continuar.',
    ),
    'Sesión finalizada (código {code}).': (
        'Session ended (code {code}).',
        'Sessão encerrada (código {code}).',
    ),
    'Selecciona UN5 o UN6.': (
        'Select UN5 or UN6.',
        'Selecione UN5 ou UN6.',
    ),
    'El servidor no publicó un identificador válido para {kind}': (
        'The server did not publish a valid identifier for {kind}',
        'O servidor não publicou um identificador válido para {kind}',
    ),
    'El archivo excede el tamaño esperado.': (
        'The file exceeds the expected size.',
        'O arquivo excede o tamanho esperado.',
    ),
    'La descarga no coincide con el archivo publicado: {kind}': (
        'The download does not match the published file: {kind}',
        'O download não corresponde ao arquivo publicado: {kind}',
    ),
    'Los símbolos no contienen NetPad.': (
        'The symbols do not include NetPad.',
        'Os símbolos não incluem o NetPad.',
    ),
    'Modo de conexión desconocido.': (
        'Unknown connection mode.',
        'Modo de conexão desconhecido.',
    ),
    'Rol desconocido.': (
        'Unknown role.',
        'Função desconhecida.',
    ),
    'Selecciona una sala válida del servidor.': (
        'Select a valid server room.',
        'Selecione uma sala válida do servidor.',
    ),
    '{section}: selecciona DualShock 2 en ARMSX2 (actual: {value}).': (
        '{section}: select DualShock 2 in ARMSX2 (current: {value}).',
        '{section}: selecione DualShock 2 no ARMSX2 (atual: {value}).',
    ),
    'Abre Naruto en ARMSX2.': (
        'Open Naruto in ARMSX2.',
        'Abra Naruto no ARMSX2.',
    ),
    'El juego abierto no coincide con el seleccionado.': (
        'The running game does not match your selection.',
        'O jogo aberto não corresponde ao jogo selecionado.',
    ),
    'Falta el estado compartido preparado en el slot 1 de ARMSX2.': (
        'The prepared shared save state is missing from ARMSX2 slot 1.',
        'O estado salvo compartilhado está faltando no slot 1 do ARMSX2.',
    ),
    'Creación cancelada.': (
        'Match creation canceled.',
        'Criação da partida cancelada.',
    ),
    'No se pudo preparar NetPad en 90 s. {detail}': (
        'NetPad setup timed out after 90 s. {detail}',
        'Não foi possível preparar o NetPad em 90 s. {detail}',
    ),
    'Prepara primero los archivos compartidos.': (
        'Prepare the shared files first.',
        'Prepare os arquivos compartilhados primeiro.',
    ),
    'No se pudo verificar Discord. Revisa la sesión en la pestaña Discord.': (
        'Could not verify Discord. Check your session on the Discord tab.',
        'Não foi possível verificar o Discord. Confira a sessão na aba Discord.',
    ),
    'La sala no usa el estado del juego seleccionado.': (
        'The room does not use the save state for the selected game.',
        'A sala não usa o estado salvo do jogo selecionado.',
    ),
    'Estado, mandos y hook comprobados. Conectando…': (
        'Save state, controllers and hook verified. Connecting…',
        'Estado salvo, controles e hook verificados. Conectando…',
    ),
    'Liberando controles. Mantén ARMSX2 visible…': (
        'Releasing controls. Keep ARMSX2 visible…',
        'Liberando os controles. Mantenha o ARMSX2 visível…',
    ),
    'No se pudieron liberar los controles. Abre ARMSX2 y recarga un estado o reinicia el juego.': (
        'Could not release the controls. Open ARMSX2 and reload a save state or restart the game.',
        'Não foi possível liberar os controles. Abra o ARMSX2 e recarregue um estado salvo ou reinicie o jogo.',
    ),
    'KOTH · Descargando los archivos de la partida. Vuelve a ARMSX2.': (
        'KOTH · Downloading match files. Return to ARMSX2.',
        'KOTH · Baixando os arquivos da partida. Volte ao ARMSX2.',
    ),
    'KOTH · La sesión terminó: {error}': (
        'KOTH · Session ended: {error}',
        'KOTH · A sessão terminou: {error}',
    ),
    'KOTH perdió la conexión con Django.': (
        'KOTH lost its connection to Django.',
        'O KOTH perdeu a conexão com o Django.',
    ),
    'KOTH móvil requiere que la pareja utilice ZeroTier.': (
        'Mobile KOTH requires both players to use ZeroTier.',
        'O KOTH no celular exige que os dois jogadores usem ZeroTier.',
    ),
    'Falta permitir el control flotante en los ajustes de Android.': (
        'Allow the floating control in Android settings.',
        'Permita o controle flutuante nas configurações do Android.',
    ),
    'No se pudo mostrar el control flotante: {error}': (
        'Could not show the floating control: {error}',
        'Não foi possível exibir o controle flutuante: {error}',
    ),
    'sin respuesta de Android': (
        'no response from Android',
        'sem resposta do Android',
    ),
    '{player}. Arrastra para mover. Mantén pulsado un segundo y suelta para detener.': (
        '{player}. Drag to move. Hold for one second and release to stop.',
        '{player}. Arraste para mover. Pressione por um segundo e solte para parar.',
    ),
    'Estado guardado: {path}': (
        'Save state saved: {path}',
        'Estado salvo: {path}',
    ),
    'Estado existente verificado: {path}': (
        'Existing save state verified: {path}',
        'Estado salvo existente verificado: {path}',
    ),
    '\nCárgalo o cópialo en ARMSX2 por tu cuenta. Netplay usa el slot 1; este botón no modifica el emulador.': (
        '\nLoad or copy it into ARMSX2 manually. Netplay uses slot 1. The emulator was left untouched.',
        '\nCarregue ou copie o arquivo manualmente para o ARMSX2. O netplay usa o slot 1. O emulador não foi alterado.',
    ),
    'Espectador': (
        'Spectator',
        'Espectador',
    ),
    'En espera': (
        'Waiting',
        'Aguardando',
    ),
    'Esperando que Django actualice la ronda.': (
        'Waiting for Django to update the round.',
        'Aguardando a atualização da rodada pelo Django.',
    ),
    'Reproduciendo el combate.': (
        'Watching the match.',
        'Assistindo à luta.',
    ),
    'Conectando con el rival.': (
        'Connecting to the opponent.',
        'Conectando ao adversário.',
    ),
    '{event} · Preparación': (
        '{event} · Preparing',
        '{event} · Preparação',
    ),
    '{event} · En curso': (
        '{event} · Running',
        '{event} · Em andamento',
    ),
    'Inscripción confirmada en {event}. Puntos: {points}. IP actualizada. Puntos descontados: {deducted}.': (
        'Registration confirmed for {event}. Points: {points}. IP updated. Points deducted: {deducted}.',
        'Inscrição confirmada em {event}. Pontos: {points}. IP atualizado. Pontos descontados: {deducted}.',
    ),
}
