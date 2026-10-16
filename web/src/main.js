import { mount } from 'svelte';
import '@fontsource-variable/inter';
import '@fontsource/literata/400.css';
import '@fontsource/literata/600.css';
import '@fontsource/literata/400-italic.css';
import './app.css';
import App from './App.svelte';

// Metin alanlari disinda tarayicinin kendi sag tik menusu kapali (uygulamanin menuleri var).
window.addEventListener('contextmenu', (event) => {
  if (!event.target.closest('input, textarea, .selectable')) event.preventDefault();
});

export default mount(App, { target: document.getElementById('app') });
