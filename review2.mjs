import { chromium } from 'playwright';
import { mkdirSync } from 'fs';
try { mkdirSync('/tmp/screenshots'); } catch(e) {}

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();

// Login
await page.goto('http://localhost:8000/auth/login', { waitUntil: 'networkidle' });
await page.fill('#email', 'prueba@gmail.com');
await page.fill('#password', '123456');
await page.click('button[type=submit]');
await page.waitForURL('**/dashboard', { timeout: 5000 }).catch(() => {});

// Roadmap
await page.goto('http://localhost:8000/roadmaps/3', { waitUntil: 'networkidle' });
await page.screenshot({ path: '/tmp/screenshots/11_roadmap.png', fullPage: true });
console.log('✅ 11_roadmap');

// Lección
const leccionLink = await page.$('a[href*="/leccion/"]');
if (leccionLink) {
  const href = await leccionLink.getAttribute('href');
  await page.goto('http://localhost:8000' + href, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: '/tmp/screenshots/12_lesson.png', fullPage: true });
  console.log('✅ 12_lesson');
}

// Mobile - landing
const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)' });
const mpage = await mobile.newPage();
await mpage.goto('http://localhost:8000', { waitUntil: 'networkidle' });
await mpage.screenshot({ path: '/tmp/screenshots/13_mobile_landing.png', fullPage: true });
console.log('✅ 13_mobile_landing');

await mpage.goto('http://localhost:8000/auth/login', { waitUntil: 'networkidle' });
await mpage.fill('#email', 'prueba@gmail.com');
await mpage.fill('#password', '123456');
await mpage.click('button[type=submit]');
await mpage.waitForURL('**/dashboard', { timeout: 5000 }).catch(() => {});
await mpage.screenshot({ path: '/tmp/screenshots/14_mobile_dashboard.png', fullPage: true });
console.log('✅ 14_mobile_dashboard');

await browser.close();
