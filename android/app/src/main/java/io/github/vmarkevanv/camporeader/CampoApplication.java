package io.github.vmarkevanv.camporeader;

import android.app.Application;
import android.os.Handler;
import android.os.Looper;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.concurrent.*;
import javax.crypto.*;
import javax.crypto.spec.GCMParameterSpec;

public class CampoApplication extends Application {
    public static CampoApplication instance;
    public RemoteBrowser browser;
    public volatile JSONObject runtime;
    public final ExecutorService worker=Executors.newSingleThreadExecutor();
    public final CompletableFuture<JSONObject> ready=new CompletableFuture<>();
    @Override public void onCreate(){
        super.onCreate();instance=this;
        browser=new RemoteBrowser(this);
        worker.execute(()->{
            try{
                if(!Python.isStarted())Python.start(new AndroidPlatform(this));
                File publicDir=new File(getFilesDir(),"public");publicDir.mkdirs();
                for(String name:getAssets().list("public")){
                    try(InputStream in=getAssets().open("public/"+name);OutputStream out=new FileOutputStream(new File(publicDir,name))){MainActivity.copy(in,out);}
                }
                File html=new File(publicDir,"campo-reader.html");
                String source=new String(java.nio.file.Files.readAllBytes(html.toPath()),StandardCharsets.UTF_8);
                source=source.replace("</head>","<link rel=\"stylesheet\" href=\"/android-mobile.css\"><script defer src=\"/android-mobile.js\"></script></head>");
                java.nio.file.Files.write(html.toPath(),source.getBytes(StandardCharsets.UTF_8));
                runtime=new JSONObject(Python.getInstance().getModule("android_runtime").callAttr("start",getFilesDir().getAbsolutePath(),publicDir.getAbsolutePath()).toString());
                ready.complete(runtime);
            }catch(Throwable error){ready.completeExceptionally(error);}
        });
    }
    private synchronized javax.crypto.SecretKey key() throws Exception{
        KeyStore store=KeyStore.getInstance("AndroidKeyStore");store.load(null);
        String alias="campo-reader-credentials-v1";
        if(!store.containsAlias(alias)){
            KeyGenerator generator=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(alias,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setKeySize(256).build());generator.generateKey();
        }
        return (javax.crypto.SecretKey)store.getKey(alias,null);
    }
    public String seal(String clear) throws Exception{
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,key());
        return "a1."+Base64.encodeToString(cipher.getIV(),Base64.NO_WRAP)+"."+Base64.encodeToString(cipher.doFinal(clear.getBytes(StandardCharsets.UTF_8)),Base64.NO_WRAP);
    }
    public String unseal(String data) throws Exception{
        String[] parts=data.split("\\.");if(parts.length!=3||!parts[0].equals("a1"))throw new SecurityException("Invalid local credential");
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,key(),new GCMParameterSpec(128,Base64.decode(parts[1],Base64.NO_WRAP)));
        return new String(cipher.doFinal(Base64.decode(parts[2],Base64.NO_WRAP)),StandardCharsets.UTF_8);
    }
}
