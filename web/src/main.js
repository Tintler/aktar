import { mount } from 'svelte';
import '@fontsource-variable/inter';
import './app.css';
import App from './App.svelte';

// Metin alanlari disinda tarayicinin kendi sag tik menusu kapali (uygulamanin menuleri var).
window.addEventListener('contextmenu', (event) => {
  if (!event.target.closest('input, textarea, .selectable')) event.preventDefault();
});

export default mount(App, { target: document.getElementById('app') });
