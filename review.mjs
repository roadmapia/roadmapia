import { chromium } from 'playwright';
import { writeFileSync } from 'fs';

const BASE = 'http://localhost:8000';
const OUT = '/tmp/screenshots';
import { mkdirSync } from 'fs';
try { mkdirSync(OUT); } catch(e) {}

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();

const errors = [];
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });

async function shot(name, url, fn) {
  await page.goto(BASE + url, { waitUntil: 'networkidle' });
  if (fn) await fn();
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
  console.log(`✅ ${name}`);
}

// 1. Landing
await shot('01_landing', '/');

// 2. Register
await shot('02_register', '/auth/register');

// 3. Register con error (contraseña corta)
await page.goto(BASE + '/auth/register', { waitUntil: 'networkidle' });
await page.fill('#nombre', 'Test');
await page.fill('#email', 'test_error@test.com');
await page.fill('#password', '123');
await page.click('button[type=submit]');
await page.waitForTimeout(800);
await page.screenshot({ path: `${OUT}/03_register_error.png`, fullPage: true });
console.log('✅ 03_register_error');

// 4. Login
await shot('04_login', '/auth/login');

// 5. Login con error
await page.goto(BASE + '/auth/login', { waitUntil: 'networkidle' });
await page.fill('#email', 'noexiste@test.com');
await page.fill('#password', 'wrongpass');
await page.click('button[type=submit]');
await page.waitForTimeout(800);
await page.screenshot({ path: `${OUT}/05_login_error.png`, fullPage: true });
console.log('✅ 05_login_error');

// 6. Pricing (sin login)
await shot('06_pricing_nologin', '/pricing');

// 7. Dashboard (sin login → redirect)
await page.goto(BASE + '/dashboard', { waitUntil: 'networkidle' });
await page.screenshot({ path: `${OUT}/07_dashboard_nologin.png`, fullPage: true });
console.log('✅ 07_dashboard_nologin (redirect check)');

// 8. Login real
await page.goto(BASE + '/auth/login', { waitUntil: 'networkidle' });
await page.fill('#email', 'prueba@gmail.com');
await page.fill('#password', '123456');
await page.click('button[type=submit]');
await page.waitForURL('**/dashboard', { timeout: 5000 }).catch(() => {});
await page.screenshot({ path: `${OUT}/08_dashboard.png`, fullPage: true });
console.log('✅ 08_dashboard');

// 9. Nuevo roadmap
await shot('09_new_roadmap', '/roadmaps/nuevo');

// 10. Pricing con login
await shot('10_pricing_loggedin', '/pricing');

// 11. Ver un roadmap (el primero disponible)
const links = await page.$$eval('a[href*="/roadmaps/"]', els =>
  els.map(e => e.href).filter(h => h.match(/roadmaps\/\d+$/))[0]
);
if (links) {
  await page.goto(links, { waitUntil: 'networkidle' });
  await page.screenshot({ path: `${OUT}/11_roadmap_view.png`, fullPage: true });
  console.log('✅ 11_roadmap_view');

  // 12. Ver primera lección
  const leccionLink = await page.$('a[href*="/leccion/"]');
  if (leccionLink) {
    await leccionLink.click();
    await page.waitForURL('**/leccion/**', { timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(1000);
    await page.screenshot({ path: `${OUT}/12_lesson.png`, fullPage: true });
    console.log('✅ 12_lesson');
  }
}

// Console errors
if (errors.length > 0) {
  console.log('\n❌ ERRORES DE CONSOLA:');
  errors.forEach(e => console.log('  -', e));
} else {
  console.log('\n✅ Sin errores de consola JS');
}

await browser.close();
console.log('\nScreenshots guardados en /tmp/screenshots/');
