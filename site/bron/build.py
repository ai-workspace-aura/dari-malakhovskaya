"""Собирает site/bron/getcourse-block.html из стилей и подвала site/main.
Запуск из корня проекта: python3 site/bron/build.py "$PWD"
"""
import re, sys
root = sys.argv[1]
s = open(root + "/site/main/getcourse-block.html", encoding="utf-8").read()
head = s[:s.index('<div class="ds">')]
head = re.sub(r'^<!--.*?-->\n<!--.*?-->\n', '''<!-- Союз с собой — бесплатная бронь места (2-й день тренинга). Вставлять в HTML-блок GetCourse целиком. Стили и подвал взяты из основного сайта (site/main).
     АДРЕС СТРАНИЦЫ: school.dari-malakhovskaya.ru/bron -->
<!-- ФОРМА: под этим HTML-блоком поставить блок «Форма» GetCourse с полями: имя, телефон, ник в Telegram (+ согласия). Заголовок у формы можно не писать —
     скрипт сам перенесёт форму в карточку справа и скроет её заголовок. Текст кнопки в форме: «Забронировать место». -->
''', head, count=1, flags=re.S)
i = s.index('  <footer class="footer">'); footer = s[i:s.index('</footer>', i) + 9]

css = r'''<style>
  /* Страница брони */
  .ds .bron{position:relative;overflow:hidden;background:var(--esp);color:#fff}
  .ds .bron::before{content:"";position:absolute;inset:0;background:radial-gradient(60% 80% at 80% 30%,rgba(107,63,160,.34),transparent 62%),radial-gradient(50% 60% at 10% 90%,rgba(107,63,160,.16),transparent 60%);pointer-events:none}
  .ds .bron-grid{position:relative;display:grid;grid-template-columns:minmax(0,1.05fr) minmax(360px,.95fr);gap:clamp(32px,5vw,88px);align-items:center;min-height:100vh;min-height:100svh;padding:clamp(40px,5vw,72px) 0}
  .ds .bron .eyebrow{margin-bottom:22px;font-size:14px}
  .ds .bron h1{font:400 clamp(48px,5.6vw,92px)/.94 var(--display);text-transform:uppercase;letter-spacing:-.03em;color:var(--sand)}
  .ds .bron h1 span{display:block;white-space:nowrap}
  .ds .bron h1 .indent{padding-left:.6em}
  .ds .bron-lead{max-width:22em;margin-top:28px;font:400 clamp(20px,1.9vw,26px)/1.2 var(--display);letter-spacing:-.03em;color:#fff}
  .ds .bron-facts{display:flex;flex-wrap:wrap;gap:10px;margin-top:32px;padding:0;list-style:none}
  .ds .bron-facts li{display:inline-flex;align-items:center;gap:10px;min-height:40px;padding:0 16px;border:1px solid var(--hair-dark);border-radius:999px;background:rgba(201,166,232,.08);font:400 14px/1 var(--display);color:var(--sand)}
  .ds .bron-facts svg{width:18px;height:18px;flex:none}
  .ds .bron-card{position:relative;padding:36px 32px 30px;border-radius:var(--r);background:#FCFAF7;color:#1A1A1A;box-shadow:0 30px 80px rgba(0,0,0,.35)}
  .ds .bron-card h2{font:400 30px/1 var(--display);text-transform:uppercase;letter-spacing:-.03em;color:#1A1A1A}
  .ds .bron-card .bron-card-sub{margin-top:10px;font-size:14px;line-height:1.45;color:#6B6570}
  .ds .bron-card .bron-form{margin-top:24px}
  .ds .bron-wait{margin:0;font-size:14px;line-height:1.45;color:#6B6570}
  .ds .bron-note{margin-top:16px;font-size:12px;line-height:1.45;color:#8A8490;text-align:center}

  /* Нативная форма GetCourse внутри карточки */
  .ds .bron-form .lt-block,.ds .bron-form .lt-block-wrapper,.ds .bron-form .container,.ds .bron-form .row,.ds .bron-form [class*="col-"],.ds .bron-form .modal-block-content{
    float:none!important;width:100%!important;max-width:none!important;margin:0!important;padding:0!important;background:transparent!important;box-shadow:none!important;min-height:0!important}
  .ds .bron-form .f-header,.ds .bron-form h1,.ds .bron-form h2,.ds .bron-form h3{display:none!important}
  .ds .bron-form .builder-item{margin:0 0 12px!important}
  .ds .bron-form input.f-input,.ds .bron-form input.form-control,.ds .bron-form input[type="text"],.ds .bron-form input[type="email"],.ds .bron-form input[type="tel"]{
    display:block!important;width:100%!important;max-width:100%!important;min-height:56px!important;margin:0 0 12px!important;
    padding:14px 16px!important;border:1px solid #E2DCE8!important;border-radius:10px!important;
    background:#fff!important;color:#1A1A1A!important;font:400 15px/1.4 var(--text)!important;
    box-shadow:none!important;outline:none!important;transition:border-color .18s ease,box-shadow .18s ease}
  .ds .bron-form .f-input-wrapper input{margin-bottom:0!important}
  .ds .bron-form .f-input-wrapper{margin:0 0 12px!important}
  .ds .bron-form input::placeholder{color:#8A8490!important;opacity:1}
  .ds .bron-form input:focus{border-color:#6B3FA0!important;box-shadow:0 0 0 3px rgba(107,63,160,.14)!important}
  .ds .bron-form button[type="submit"],.ds .bron-form input[type="submit"],.ds .bron-form .btn-success{
    display:flex!important;align-items:center!important;justify-content:center!important;width:100%!important;
    min-height:58px!important;margin:8px 0 0!important;padding:12px 24px!important;border:0!important;
    border-radius:10px!important;background:#6B3FA0!important;color:#fff!important;text-align:center!important;
    font:400 16px/1.2 var(--display)!important;letter-spacing:-.02em;white-space:normal!important;cursor:pointer!important;
    box-shadow:none!important;transition:background .18s ease,transform .18s ease}
  .ds .bron-form button[type="submit"]:hover,.ds .bron-form input[type="submit"]:hover{background:#3E2468!important;transform:translateY(-1px)}
  .ds .bron-form .f-input-wrapper[data-type="checkbox"]{display:block!important;margin:4px 0 10px!important}
  .ds .bron-form .f-input-wrapper[data-type="checkbox"]>.field-label{display:flex!important;align-items:flex-start!important;gap:10px!important;margin:0!important;color:#1A1A1A!important;font:400 13px/1.4 var(--text)!important;font-style:normal!important}
  .ds .bron-form input[type="checkbox"]{display:block!important;flex:0 0 18px!important;width:18px!important;height:18px!important;margin:0!important;accent-color:#6B3FA0;cursor:pointer}
  .ds .bron-form .field-description-block{margin:2px 0 0 28px!important;color:#6B6570!important;font:400 12px/1.45 var(--text)!important}
  .ds .bron-form .field-description-block a,.ds .bron-form .field-label a{color:#6B3FA0!important;text-decoration:underline!important;text-underline-offset:2px}
  .ds .bron-form .form-result-block:empty{display:none}

  html:not(.is-phone) .ds .bron-grid{min-height:100svh}
  @media (max-width:1180px){
    html:not(.is-phone) .ds .bron-grid{grid-template-columns:1fr;max-width:620px;margin:0 auto;min-height:0;padding:72px 0}
  }
  html.is-phone .ds .bron-grid{grid-template-columns:1fr;gap:28px;min-height:0;padding:40px 0 36px}
  html.is-phone .ds .bron .eyebrow{font-size:12px;margin-bottom:16px}
  html.is-phone .ds .bron h1{font-size:clamp(38px,11.4vw,64px)}
  html.is-phone .ds .bron h1 .indent{padding-left:0}
  html.is-phone .ds .bron-lead{margin-top:18px}
  html.is-phone .ds .bron-facts{margin-top:22px;gap:8px}
  html.is-phone .ds .bron-facts li{min-height:36px;padding:0 14px;font-size:13px}
  html.is-phone .ds .bron-card{padding:26px 18px 22px;border-radius:16px}
  html.is-phone .ds .bron-card h2{font-size:24px}
</style>
'''

cal = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/></svg>'
gift = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>'

section = f'''  <!-- Бронь места -->
  <section class="bron on-dark" id="top">
    <div class="col bron-grid">
      <div class="bron-copy">
        <p class="eyebrow">Союз с собой · 5 сезон</p>
        <h1><span>Забронируй</span><span class="indent">своё место</span></h1>
        <p class="bron-lead">Оставь контакты, и место в 5&nbsp;сезоне <span style="white-space:nowrap">«Союза с собой»</span> закрепится за тобой.</p>
        <ul class="bron-facts">
          <li>{gift}Бронь бесплатная</li>
          <li>{cal}Старт 15 декабря 2026 года</li>
        </ul>
      </div>
      <div class="bron-card">
        <h2>Бронь места</h2>
        <p class="bron-card-sub">Имя, телефон и ник в Telegram — этого достаточно.</p>
        <div class="bron-form" id="bron-form">
          <p class="bron-wait" id="bron-wait" hidden>Форма загружается…</p>
        </div>
      </div>
    </div>
  </section>
'''

script = r'''<script>
(function(){
  // Переносим блок формы GetCourse в карточку. Вне GetCourse показываем макет полей.
  var box=document.getElementById("bron-form"),wait=document.getElementById("bron-wait");
  if(!box)return;
  var isPreview=!/getcourse|dari-malakhovskaya\.ru/.test(location.hostname);
  function preview(){
    box.insertAdjacentHTML("beforeend",
      '<div class="f-input-wrapper"><input type="text" placeholder="Ваше имя"></div>'+
      '<div class="f-input-wrapper"><input type="tel" placeholder="Телефон"></div>'+
      '<div class="f-input-wrapper"><input type="text" placeholder="Ник в Telegram, например @name"></div>'+
      '<div class="f-input-wrapper" data-type="checkbox"><label class="field-label"><input type="checkbox"><span>Согласна на обработку <a href="https://school.dari-malakhovskaya.ru/persdatacept">персональных данных</a></span></label></div>'+
      '<div class="f-input-wrapper" data-type="checkbox"><label class="field-label"><input type="checkbox"><span>Согласна на получение <a href="https://school.dari-malakhovskaya.ru/soglasie-reklama">рассылки</a></span></label></div>'+
      '<button type="submit" disabled>Забронировать место</button>');
  }
  function findForm(){
    var forms=document.querySelectorAll("form");
    for(var i=0;i<forms.length;i++){
      if(box.contains(forms[i]))continue;
      return forms[i].closest(".lt-block")||forms[i];
    }
    return null;
  }
  var tries=0;
  (function attempt(){
    var f=findForm();
    if(f){box.appendChild(f);if(wait)wait.hidden=true;return;}
    if(isPreview){preview();return;}
    if(wait)wait.hidden=false;
    if(++tries<40)setTimeout(attempt,250);
  })();
})();
</script>
'''

out = head + css + '<div class="ds">\n' + section + '\n' + footer + '\n</div>\n' + script
open(root + "/site/bron/getcourse-block.html", "w", encoding="utf-8").write(out)
print("ok", len(out))
