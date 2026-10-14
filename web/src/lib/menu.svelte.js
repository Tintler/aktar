// Sag tik menusu (components/MenuHost.svelte cizer).
// items: [{label, icon, action, disabled, danger} | 'sep']
export const menu = $state({ current: null });

export function openMenu(event, items) {
  event.preventDefault();
  event.stopPropagation();
  menu.current = { x: event.clientX, y: event.clientY, items };
}

export function closeMenu() {
  menu.current = null;
}
