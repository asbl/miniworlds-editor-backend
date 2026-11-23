/* Run with NODE_PATH pointing to Playwright and MINIWORLDS_TEST_URL pointing to an isolated test server. */
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const base = process.env.MINIWORLDS_TEST_URL || 'http://127.0.0.1:8896';
(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.CHROMIUM_PATH ? {executablePath:process.env.CHROMIUM_PATH} : {}), args:['--no-sandbox']});
  try {
    const context = await browser.newContext({ignoreHTTPSErrors:true});
    const page = await context.newPage(), errors=[];
    page.setDefaultTimeout(15000);
    page.on('pageerror', e=>errors.push(e.message));
    const post = async (path, data, csrf) => {
      const response = await context.request.post(base+path,{data,headers:csrf ? {'X-CSRF-Token':csrf} : {}});
      assert.equal(response.status(),200,await response.text()); return response.json();
    };
    const admin = await post('/api/auth/login',{email:process.env.MINIWORLDS_TEST_ADMIN || 'admin@example.test',password:process.env.MINIWORLDS_TEST_PASSWORD || 'local-test-password',role:'admin'});
    // Administrative quota fields display MB and persist bytes without changing the limits.
    await page.goto(base+'/admin');
    await page.evaluate(csrf=>sessionStorage.setItem('csrf',csrf),admin.csrf);
    const settings=await (await context.request.get(base+'/api/admin/settings')).json();
    await page.waitForFunction(()=>document.querySelector('[name=teacher_quota_cap]').value!=='');
    assert.equal(Number(await page.locator('[name=teacher_quota_cap]').inputValue()),settings.teacher_quota_cap/1048576);
    const saved=page.waitForResponse(r=>r.url().endsWith('/api/admin/settings') && r.request().method()==='PATCH');
    await page.locator('#settings-form button').click();assert.equal((await saved).status(),200);
    assert.deepEqual(await (await context.request.get(base+'/api/admin/settings')).json(),settings);
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.setViewportSize({width:1280,height:900});
    const invite = await post('/api/admin/invites',{school:'Browser-Regressionsprüfung'},admin.csrf);
    const teacher = await post('/api/auth/claim',{invite_code:invite.code,email:`browser-${Date.now()}@example.test`,password:'browser-test-password'});
    await page.addInitScript(() => {
      sessionStorage.setItem('miniworlds-answers:legacy:1', JSON.stringify({'1':{text:'PRIVATE_LOCAL_ANSWER'},'2':{checked:true,text:'PRIVATE_LOCAL_ANSWER'}}));
    });
    await page.goto(base+'/teacher');
    assert.deepEqual(await page.evaluate(()=>JSON.parse(sessionStorage.getItem('miniworlds-answers:legacy:1'))),{'2':{checked:true}});
    await page.evaluate(()=>sessionStorage.removeItem('miniworlds-answers:legacy:1'));
    await page.locator('#course-create-form [name=title]').fill('Informatik Browserklasse');
    await page.locator('#course-create-form [name=school_year]').fill('2026/27');
    await page.locator('#course-create-form button').click();
    await page.locator('#courses-list').getByText(/Informatik Browserklasse/).waitFor();
    const courses = await (await context.request.get(base+'/api/teacher/courses')).json();
    const cid = courses.courses[0].id;
    await page.locator('#project-create-form [name=count]').fill('2');
    await page.locator('#project-create-form [name=course_id]').selectOption(String(cid));
    await page.locator('#project-create-form button').click();
    await page.locator('#projects-table tbody tr').nth(1).waitFor();
    const codes=(await page.locator('#new-codes').innerText()).trim().split('\n');assert.equal(codes.length,2);
    assert.equal(await page.locator('#bulk-lock').isDisabled(),true);
    await page.locator('.project-select').first().check();assert.equal(await page.locator('#bulk-lock').isEnabled(),true);
    await page.locator('.project-select').first().uncheck();
    await page.locator('.action-menu summary').first().click();
    await page.getByRole('button',{name:'Zugang einstellen'}).first().click();
    await page.locator('dialog [name=days]').fill('180');
    await page.locator('dialog button').getByText('Speichern',{exact:true}).click();
    await page.locator('dialog').waitFor({state:'detached'});
    assert.equal((await (await context.request.get(base+'/api/teacher/projects')).json()).projects.find(p=>p.code_readonly_days===180)?.code_readonly_days,180);
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.setViewportSize({width:1280,height:900});
    await page.locator('[data-tab=tasks]').click();
    await page.locator('#task-create-form [name=title]').fill('Bau ein Spiel');
    await page.locator('#task-create-form [name=course_id]').selectOption(String(cid));
    await page.locator('#task-create-form [name=description]').fill('Entwickle eine Bewegung.');
    await page.locator('#task-create-form button').click();
    const card=page.locator('#tasks-list article').first();await card.getByRole('heading',{name:'Bau ein Spiel',exact:true}).waitFor();
    assert.equal(await card.locator('select[name=kind] option[value=textarea]').count(),0);
    await card.locator('select[name=kind]').selectOption('checkbox');
    await card.locator('input[name=prompt]').fill('Programm getestet');
    await card.getByRole('button',{name:'Aufgabenteil hinzufügen'}).click();
    await page.locator('#tasks-list').getByText('Programm getestet',{exact:false}).waitFor();
    await card.getByRole('button',{name:'Klasse und neuen Projekten zuweisen'}).click();
    await page.waitForFunction(()=>document.getElementById('tasks-list').textContent.includes('2 Zuweisungen'));
    assert.ok(await page.locator('#tasks-list').getByText('Programm getestet', {exact:false}).count());
    assert.deepEqual(errors, []);
    console.log('PASS: Admin-Einstellungen, Klassen, Projektcodes, Zugang, Aufgaben und Zuweisungen. Schüler- und Vorschauabläufe werden mit dem vollständigen Editor geprüft.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
