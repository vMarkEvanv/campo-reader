package io.github.vmarkevanv.camporeader;

import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import com.chaquo.python.Python;
import org.junit.*;
import org.junit.runner.RunWith;
import org.json.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class LocalAppTest {
    ActivityScenario<MainActivity> activity;
    CampoApplication app;
    @Before public void launch()throws Exception{
        activity=ActivityScenario.launch(MainActivity.class);
        activity.onActivity(a->app=(CampoApplication)a.getApplication());
        app.ready.get(90,TimeUnit.SECONDS);
        waitJs("document.getElementById('android-about')!==null", "true");
        waitJs("document.getElementById('add').disabled", "false");
    }
    @After public void close(){activity.close();}
    String js(String script)throws Exception{
        CompletableFuture<String> done=new CompletableFuture<>();activity.onActivity(a->a.getAppWebView().evaluateJavascript(script,done::complete));return done.get(15,TimeUnit.SECONDS);
    }
    void waitJs(String script,String expected)throws Exception{long until=System.currentTimeMillis()+45000;String value="";while(System.currentTimeMillis()<until){value=js(script);if(expected.equals(value))return;Thread.sleep(150);}fail("UI condition did not settle: "+script+" -> "+value);}
    @Test public void localRuntimeAndMobileWorkflow()throws Exception{
        assertTrue(app.runtime.getString("origin").startsWith("http://127.0.0.1:"));
        assertTrue(Python.getInstance().getModule("android_runtime").callAttr("diagnostics").toBoolean());
        assertEquals("true",js("document.documentElement.scrollWidth<=innerWidth"));
        assertEquals("true",js("document.documentElement.classList.contains('android-app')"));
        js("document.getElementById('add').click();document.getElementById('label').value='Android test';document.querySelector('#add-form .primary').click()");
        waitJs("document.getElementById('accounts').options[0].textContent",JSONObject.quote("Android test"));
        for(String view:new String[]{"courses","grades","progress","documents","calendar"}){
            js("document.getElementById('tab-"+view+"').click()");assertEquals("false",js("document.getElementById('"+view+"').hidden"));
            assertEquals("true",js("document.documentElement.scrollWidth<=innerWidth"));
        }
        assertEquals("1",js("document.querySelectorAll('#week>.mobile-day-active').length"));
        js("document.getElementById('settings').click()");assertEquals("true",js("document.getElementById('settings-dialog').open"));
        activity.onActivity(a->a.getOnBackPressedDispatcher().onBackPressed());waitJs("document.getElementById('settings-dialog').open","false");
        // Reload uses the on-device SQLite account without any online service.
        activity.onActivity(a->a.getAppWebView().reload());waitJs("document.getElementById('accounts').options[0].textContent",JSONObject.quote("Android test"));
        String encrypted=app.seal("synthetic-local-value");assertFalse(encrypted.contains("synthetic-local-value"));assertEquals("synthetic-local-value",app.unseal(encrypted));
        try{app.unseal(encrypted.substring(0,encrypted.length()-5)+"AAAAA");fail("Tampered ciphertext accepted");}catch(Exception expected){}
    }
    @Test public void officialBrowserAdapterIsIsolated()throws Exception{
        assertTrue(RemoteBrowser.official("https://www.campo.fau.de/qisserver/"));assertFalse(RemoteBrowser.official("https://www.campo.fau.de.evil.example/"));assertFalse(RemoteBrowser.official("http://www.campo.fau.de/"));assertFalse(RemoteBrowser.official("https://evil@www.campo.fau.de/"));
        JSONObject blocked=new JSONObject(app.browser.call("goto","{\"url\":\"http://192.168.2.60:8080\"}"));assertFalse(blocked.getBoolean("ok"));
        CompletableFuture<Boolean> loaded=new CompletableFuture<>();
        activity.onActivity(a->{app.browser.view.loadDataWithBaseURL("https://www.campo.fau.de/qisserver/fixture","<html><body><a id='x:logoutLink'></a><button id='x:avatarInfobox:open' title='My profile: Synthetic Student'></button><select id='term'><option value='a'>Summer semester 2026</option><option value='b'>Winter semester 2026</option></select><button id='click' onclick=\"document.body.dataset.clicked='yes'\">Read</button></body></html>","text/html","UTF-8",null);loaded.complete(true);});loaded.get();
        Thread.sleep(800);
        String result=Python.getInstance().getModule("android_adapter_test").callAttr("check").toString();assertEquals("passed",result);
    }
}
