def check():
    from android_browser import Page,rpc
    from campo_backend.campo_source import scripts
    class Context:
        def cookies(self,url):return []
    page=Page(Context())
    page.goto("https://www.campo.fau.de/qisserver/fixture")
    import time
    deadline=time.monotonic()+15
    while True:
        state=page.evaluate(scripts.STATE)
        if state['logged_in'] and state['identity']=='Synthetic':break
        if time.monotonic()>deadline:raise AssertionError('Synthetic fixture not ready: '+repr(state))
        time.sleep(.15)
    assert page.evaluate('typeof CampoMobile')=='undefined'
    assert page.locator('#click').is_visible()
    page.locator('#click').click()
    assert page.evaluate('document.body.dataset.clicked')=='yes'
    page.locator('#term').select_option('b')
    assert page.evaluate('document.querySelector("#term").value')=='b'
    assert isinstance(rpc('cookies'),list)
    return 'passed'
