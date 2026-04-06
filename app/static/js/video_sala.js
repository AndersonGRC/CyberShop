/**
 * video_sala.js — Wrapper del Jitsi Meet External API.
 *
 * Controla el lobby personalizado y la instanciación del iframe
 * de Jitsi Meet para videollamadas dentro de CyberShop.
 */

(function () {
    'use strict';

    var api = null;
    var config = window.VIDEO_CONFIG;

    function iniciarJitsi() {
        if (!config || !config.salaActiva) return;

        var lobby = document.getElementById('video-lobby');
        var container = document.getElementById('jitsi-container');
        var ended = document.getElementById('video-ended');

        lobby.style.display = 'none';
        container.style.display = 'block';

        var options = {
            roomName: config.roomName,
            parentNode: container,
            width: '100%',
            height: '100%',
            userInfo: {
                displayName: config.displayName,
                email: config.email
            },
            configOverwrite: {
                startWithAudioMuted: true,
                startWithVideoMuted: false,
                prejoinPageEnabled: false,
                disableDeepLinking: true,
                toolbarButtons: [
                    'camera',
                    'microphone',
                    'desktop',
                    'chat',
                    'raisehand',
                    'tileview',
                    'fullscreen',
                    'hangup',
                    'participants-pane',
                    'settings',
                    'select-background',
                    'toggle-camera'
                ],
                hideConferenceSubject: false
            },
            interfaceConfigOverwrite: {
                SHOW_JITSI_WATERMARK: false,
                SHOW_WATERMARK_FOR_GUESTS: false,
                DEFAULT_BACKGROUND: '#0e1b33',
                MOBILE_APP_PROMO: false,
                HIDE_INVITE_MORE_HEADER: true
            }
        };

        api = new JitsiMeetExternalAPI(config.domain, options);

        // Establecer contraseña de sala si existe
        if (config.password && config.isModerator) {
            api.addEventListener('participantRoleChanged', function (event) {
                if (event.role === 'moderator') {
                    api.executeCommand('password', config.password);
                }
            });
        }

        // Si tiene contraseña y no es moderador, ingresarla
        if (config.password && !config.isModerator) {
            api.addEventListener('passwordRequired', function () {
                api.executeCommand('password', config.password);
            });
        }

        // Cuando se cierra la llamada
        api.addEventListener('readyToClose', function () {
            if (api) {
                api.dispose();
                api = null;
            }
            container.style.display = 'none';
            ended.style.display = 'flex';
        });

        // Cuando el usuario sale de la conferencia
        api.addEventListener('videoConferenceLeft', function () {
            if (api) {
                api.dispose();
                api = null;
            }
            container.style.display = 'none';
            ended.style.display = 'flex';
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        var btnUnirse = document.getElementById('btn-unirse');
        if (btnUnirse) {
            btnUnirse.addEventListener('click', iniciarJitsi);
        }
    });
})();
