// Mark hosted before first paint. Shared client owns theme and platform behaviour.
if (window.parent !== window) document.documentElement.setAttribute('data-wz-hosted', '');
