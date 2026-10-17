package io.github.vmarkevanv.camporeader;

import android.content.Context;
import android.graphics.Bitmap;
import android.net.Uri;
import android.net.http.SslError;
import android.os.*;
import android.webkit.*;
import org.json.*;
import java.io.*;
import java.net.*;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Consumer;

/** Read-only Campo adapter: no JavaScript interface is exposed to official pages. */
public class RemoteBrowser {
    final WebView view;
    final Handler main=new Handler(Looper.getMainLooper());
    boolean loading=false;
    String error="";
    int sequence=0;
    final Queue<JSONObject> downloads=new ConcurrentLinkedQueue<>();
    final Set<String> origins=new LinkedHashSet<>();
    final List<WebView> popups=new ArrayList<>();
    final Context context;
    RemoteBrowser(Context context){
        this.context=context;view=create();
    }
    public static boolean official(String url){
        Uri u=Uri.parse(url);String host=u.getHost();
        return "https".equals(u.getScheme())&&host!=null&&(host.equals("fau.de")||host.endsWith(".fau.de"))&&(u.getPort()==-1||u.getPort()==443)&&u.getUserInfo()==null;
    }
    WebResourceResponse blocked(){return new WebResourceResponse("text/plain","UTF-8",403,"Blocked",Collections.emptyMap(),new ByteArrayInputStream(new byte[0]));}
    WebView create(){
        WebView w=new WebView(context);WebSettings s=w.getSettings();
        s.setJavaScriptEnabled(true);s.setDomStorageEnabled(false);s.setAllowFileAccess(false);s.setAllowContentAccess(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);s.setSupportMultipleWindows(true);s.setJavaScriptCanOpenWindowsAutomatically(true);
        s.setUserAgentString("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36");
        CookieManager.getInstance().setAcceptThirdPartyCookies(w,false);
        w.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView v,WebResourceRequest r){if(official(r.getUrl().toString()))return false;error="不支持的登录跳转，请在 Campo 官方页面检查账号。";return true;}
            @Override public WebResourceResponse shouldInterceptRequest(WebView v,WebResourceRequest r){if(!official(r.getUrl().toString()))return blocked();
                if("GET".equals(r.getMethod())&&pdfEndpoint(r.getUrl().toString())){try{return capturePdf(r.getUrl().toString());}catch(Exception e){return null;}}
                return null;}
            @Override public void onPageStarted(WebView v,String url,Bitmap icon){if(v==view){sequence++;loading=true;error="";}if(official(url)){Uri u=Uri.parse(url);origins.add("https://"+u.getHost());}}
            @Override public void onPageFinished(WebView v,String url){if(v==view)loading=false;}
            @Override public void onReceivedSslError(WebView v,SslErrorHandler h,SslError e){h.cancel();error="Campo 的安全连接验证失败。";loading=false;}
            @Override public void onReceivedError(WebView v,WebResourceRequest r,WebResourceError e){if(r.isForMainFrame()){error="Campo 暂时无法连接。";loading=false;}}
        });
        w.setDownloadListener((url,ua,disposition,mime,length)->{if(official(url)){try{downloads.add(new JSONObject().put("url",url));}catch(JSONException ignored){}}loading=false;});
        w.setWebChromeClient(new WebChromeClient(){
            @Override public boolean onCreateWindow(WebView v,boolean dialog,boolean gesture,Message result){
                WebView popup=create();popups.add(popup);((WebView.WebViewTransport)result.obj).setWebView(popup);result.sendToTarget();return true;
            }
        });return w;
    }
    static boolean pdfEndpoint(String url){
        String path=Uri.parse(url).getPath();String lower=url.toLowerCase(Locale.ROOT);
        return path!=null&&(path.toLowerCase(Locale.ROOT).endsWith(".pdf")||lower.contains("reportfile")||lower.contains("downloadreport")||lower.contains("/reporting/"));
    }
    // Consume the original GET response once: generated report URLs may be single-use.
    WebResourceResponse capturePdf(String url)throws Exception{
        for(int redirect=0;redirect<5;redirect++){
            if(!official(url))throw new SecurityException();
            HttpURLConnection c=(HttpURLConnection)new URL(url).openConnection();c.setInstanceFollowRedirects(false);c.setConnectTimeout(10000);c.setReadTimeout(20000);
            String cookies=CookieManager.getInstance().getCookie(url);if(cookies!=null)c.setRequestProperty("Cookie",cookies);
            c.setRequestProperty("User-Agent","Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36");
            int status=c.getResponseCode();
            for(Map.Entry<String,List<String>> entry:c.getHeaderFields().entrySet())if("Set-Cookie".equalsIgnoreCase(entry.getKey()))for(String cookie:entry.getValue())CookieManager.getInstance().setCookie(url,cookie);
            if(status>=300&&status<400){String location=c.getHeaderField("Location");c.disconnect();if(location==null)throw new IOException();url=new URL(new URL(url),location).toString();continue;}
            String type=c.getContentType(),disposition=c.getHeaderField("Content-Disposition");
            if(status!=200){c.disconnect();throw new IOException();}
            boolean pdf=(type!=null&&type.toLowerCase(Locale.ROOT).contains("application/pdf"))||(disposition!=null&&disposition.toLowerCase(Locale.ROOT).contains(".pdf"));
            if(!pdf){InputStream in=c.getInputStream();return new WebResourceResponse(type==null?"text/html":type.split(";")[0],"UTF-8",new FilterInputStream(in){@Override public void close()throws IOException{try{super.close();}finally{c.disconnect();}}});}
            byte[] content;try(InputStream in=c.getInputStream();ByteArrayOutputStream out=new ByteArrayOutputStream()){
                byte[] buffer=new byte[32768];int n;while((n=in.read(buffer))!=-1){if(out.size()+n>10*1024*1024)throw new IOException();out.write(buffer,0,n);}content=out.toByteArray();
            }finally{c.disconnect();}
            if(content.length<5||!new String(content,0,5,java.nio.charset.StandardCharsets.US_ASCII).equals("%PDF-"))throw new IOException();
            recordPdf(content);
            return new WebResourceResponse("text/plain","UTF-8",204,"No Content",Collections.emptyMap(),new ByteArrayInputStream(new byte[0]));
        }throw new IOException();
    }
    void recordPdf(byte[] content)throws Exception{
        if(content.length<5||content.length>10*1024*1024||!new String(content,0,5,java.nio.charset.StandardCharsets.US_ASCII).equals("%PDF-"))throw new IOException();
        File dir=new File(context.getCacheDir(),"report-downloads");dir.mkdirs();File file=File.createTempFile("report-",".pdf",dir);try(OutputStream out=new FileOutputStream(file)){out.write(content);}
        downloads.add(new JSONObject().put("path",file.getAbsolutePath()));
    }
    public String call(String op,String payload){
        if(Looper.myLooper()==Looper.getMainLooper())throw new IllegalStateException("Browser RPC must be off the main thread");
        CompletableFuture<String> result=new CompletableFuture<>();
        main.post(()->{
            Consumer<Object> done=value->{try{result.complete(new JSONObject().put("ok",true).put("value",value==null?JSONObject.NULL:value).toString());}catch(Exception e){result.complete("{\"ok\":false,\"error\":\"手机浏览器结果不可用。\"}");}};
            try{
                JSONObject args=new JSONObject(payload);
                switch(op){
                case "goto":{
                    String url=args.getString("url");if(!official(url))throw new SecurityException();
                    loading=true;error="";view.loadUrl(url);done.accept(true);break;
                }
                case "evaluate":{
                    if(!official(view.getUrl()==null?"":view.getUrl()))throw new SecurityException();
                    String script=args.getString("script");
                    view.evaluateJavascript("(()=>{try{return JSON.stringify({ok:true,value:("+script+" )})}catch(e){return JSON.stringify({ok:false})}})()",raw->{
                        try{
                            Object decoded=new JSONTokener(raw).nextValue();JSONObject envelope=new JSONObject(String.valueOf(decoded));
                            if(!envelope.optBoolean("ok"))throw new IllegalStateException();done.accept(envelope.opt("value"));
                        }catch(Exception e){result.complete("{\"ok\":false,\"error\":\"Campo 页面尚未准备好，请重试同步。\"}");}
                    });break;
                }
                case "status":done.accept(new JSONObject().put("loading",loading).put("sequence",sequence).put("error",error));break;
                case "downloads":{JSONArray list=new JSONArray();JSONObject item;while((item=downloads.poll())!=null)list.put(item);done.accept(list);break;}
                case "cookies":{
                    JSONArray cookies=new JSONArray();Set<String> seen=new HashSet<>();origins.add("https://www.campo.fau.de");
                    for(String origin:origins)for(String path:new String[]{"/","/qisserver/"}){
                        String raw=CookieManager.getInstance().getCookie(origin+path);if(raw==null)continue;
                        for(String pair:raw.split(";")){String[] p=pair.trim().split("=",2);String host=Uri.parse(origin).getHost();String id=host+":"+p[0];if(p.length!=2||!seen.add(id))continue;
                            cookies.put(new JSONObject().put("name",p[0]).put("value",p[1]).put("domain",host).put("path","/").put("secure",true).put("httpOnly",true).put("expires",-1).put("sameSite","Lax"));
                        }
                    }done.accept(cookies);break;
                }
                case "reset":{
                    view.stopLoading();for(WebView popup:popups)popup.destroy();popups.clear();origins.clear();downloads.clear();error="";loading=false;
                    JSONArray cookies=args.getJSONObject("state").optJSONArray("cookies");
                    CookieManager cm=CookieManager.getInstance();
                    // Clear previous official account cookies, then restore the local UI cookie too.
                    cm.removeAllCookies(removed->{
                        try{
                            JSONObject runtime=CampoApplication.instance.runtime;
                            if(runtime!=null)cm.setCookie(runtime.getString("origin"),runtime.getString("cookie")+"; Path=/; HttpOnly; SameSite=Strict");
                            if(cookies!=null)for(int i=0;i<cookies.length();i++){
                                JSONObject cookie=cookies.getJSONObject(i);String domain=cookie.optString("domain").replaceFirst("^\\.","");String url="https://"+domain;
                                if(!official(url)||!cookie.getString("name").matches("[!#$%&'*+.^_`|~0-9a-zA-Z-]+")||cookie.getString("value").matches("(?s).*[;\\r\\n].*"))continue;
                                origins.add(url);String path=cookie.optString("path","/");if(!path.startsWith("/")||path.contains(";"))path="/";
                                cm.setCookie(url,cookie.getString("name")+"="+cookie.getString("value")+"; Path="+path+"; Secure; HttpOnly; SameSite=Lax");
                            }
                            cm.flush();done.accept(true);
                        }catch(Exception e){result.complete("{\"ok\":false,\"error\":\"本机登录会话无法恢复，请重新登录。\"}");}
                    });break;
                }
                case "close":view.stopLoading();for(WebView popup:popups)popup.destroy();popups.clear();done.accept(true);break;
                default:throw new IllegalArgumentException();
                }
            }catch(Exception e){try{result.complete(new JSONObject().put("ok",false).put("error",BuildConfig.DEBUG ? "浏览器适配检查: "+op+"/"+e.getClass().getSimpleName() : "手机浏览器操作未完成。").toString());}catch(Exception ignored){result.complete("{\"ok\":false}");}}
        });
        try{return result.get(35,TimeUnit.SECONDS);}catch(Exception e){return "{\"ok\":false,\"error\":\"手机浏览器响应超时，请保持应用在前台后重试。\"}";}
    }
}
