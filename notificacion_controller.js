// notificaciones.js - Lógica para mostrar las notificaciones en la interfaz web

document.addEventListener('DOMContentLoaded', () => {
    cargarNotificaciones();
});

/**
 * Consulta la API backend para obtener avisos del usuario actual
 */
function cargarNotificaciones() {
    fetch('obtener_notificaciones.php') // Endpoint que llama a obtenerPendientesPorUsuario()
        .then(response => response.json())
        .then(data => {
            const contadorElement = document.getElementById('noti-badge');
            const listaElement = document.getElementById('lista-notificaciones');

            if (!listaElement) return;

            listaElement.innerHTML = '';

            if (data.length === 0) {
                listaElement.innerHTML = '<li class="p-2 text-gray-500 text-sm">No tienes notificaciones nuevas</li>';
                if (contadorElement) contadorElement.style.display = 'none';
                return;
            }

            // Mostrar la cantidad no leída
            if (contadorElement) {
                contadorElement.innerText = data.length;
                contadorElement.style.display = 'inline-block';
            }

            // Renderizar cada notificación (puntos 7, 8 y 9)
            data.forEach(item => {
                const li = document.createElement('li');
                li.className = `p-3 border-b text-sm ${getClasePorTipo(item.tipo)}`;
                li.innerHTML = `
                    <p class="font-semibold text-gray-800">${item.mensaje}</p>
                    <span class="text-xs text-gray-400">${new Date(item.created_at).toLocaleString()}</span>
                `;
                listaElement.appendChild(li);
            });
        })
        .catch(err => console.error('Error al cargar notificaciones:', err));
}

/**
 * Retorna estilos según el tipo de evento (Puntos 7, 8 y 9)
 */
function getClasePorTipo(tipo) {
    switch (tipo) {
        case 'assignment.returned':
            return 'bg-yellow-50 border-yellow-200'; // Devolución (Punto 7)
        case 'assignment.approved':
            return 'bg-green-50 border-green-200';  // Aprobación (Punto 8)
        case 'program.authorized':
            return 'bg-blue-50 border-blue-200';    // Autorización (Punto 9)
        default:
            return 'bg-white';
    }
}