package io.github.vmarkevanv.camporeader;

import android.app.*;
import android.content.*;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.view.*;
import android.webkit.*;
import android.widget.*;
import androidx.activity.ComponentActivity;
import androidx.activity.OnBackPressedCallback;
import androidx.core.content.FileProvider;
import androidx.core.graphics.Insets;
import androidx.core.view.*;
import com.chaquo.python.Python;
import org.json.JSONObject;
import java.io.*;

public class MainActivity extends ComponentActivity {
    private WebView web;
    private TextView loading;
    private CampoApplication app;
    private ValueCallback<Uri[]> fileCallback;
    private File exportFile;
    private String exportTitle="Campo document.pdf";
    private static final int PICK_PDF=100,SAVE_PDF=101;
    @Override public void onCreate(Bundle state){
        super.onCreate(state);app=(CampoApplication)getApplication();
        WindowCompat.setDecorFitsSystemWindows(getWindow(),false);
        FrameLayout root=new FrameLayout(this);root.setBackgroundColor(Color.rgb(16,19,21));setContentView(root);
        ViewCompat.setOnApplyWindowInsetsListener(root,(v,insets)->{Insets b=insets.getInsets(WindowInsetsCompat.Type.systemBars()|WindowInsetsCompat.Type.ime());v.setPadding(b.left,b.top,b.right,b.bottom);return insets;});
        if(app.browser.view.getParent() instanceof ViewGroup)((ViewGroup)app.browser.view.getParent()).removeView(app.browser.view);
        root.addView(app.browser.view,new FrameLayout.LayoutParams(1024,900));app.browser.view.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);app.browser.view.setAlpha(0f);
        web=new WebView(this);web.setBackgroundColor(Color.rgb(16,19,21));root.addView(web,new FrameLayout.LayoutParams(-1,-1));
        WebSettings settings=web.getSettings();settings.setJavaScriptEnabled(true);settings.setDomStorageEnabled(true);settings.setAllowFileAccess(false);settings.setAllowContentAccess(false);settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);settings.setSupportZoom(false);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web,false);
        web.addJavascriptInterface(new MobileBridge(),"CampoMobile");
        web.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView w,WebResourceRequest r){String url=r.getUrl().toString();if(local(url))return false;openExternal(url);return true;}
            @Override public WebResourceResponse shouldInterceptRequest(WebView w,WebResourceRequest r){return local(r.getUrl().toString())?null:app.browser.blocked();}
            @Override public void onPageFinished(WebView w,String url){loading.setVisibility(View.GONE);}
            @Override public void onReceivedError(WebView w,WebResourceRequest r,WebResourceError e){if(r.isForMainFrame()){loading.setText("暂时无法打开本机界面\n点这里重试");loading.setVisibility(View.VISIBLE);}}
        });
        web.setWebChromeClient(new WebChromeClient(){
            @Override public boolean onShowFileChooser(WebView w,ValueCallback<Uri[]> callback,FileChooserParams params){
                if(fileCallback!=null)fileCallback.onReceiveValue(null);fileCallback=callback;
                Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("application/pdf").addCategory(Intent.CATEGORY_OPENABLE).putExtra(Intent.EXTRA_ALLOW_MULTIPLE,true);
                try{startActivityForResult(intent,PICK_PDF);}catch(ActivityNotFoundException e){fileCallback.onReceiveValue(null);fileCallback=null;toast("未找到文件选择器。");}return true;
            }
            @Override public boolean onJsConfirm(WebView w,String url,String message,JsResult result){new AlertDialog.Builder(MainActivity.this).setMessage(message).setPositiveButton("确认",(d,i)->result.confirm()).setNegativeButton("取消",(d,i)->result.cancel()).setOnCancelListener(d->result.cancel()).show();return true;}
        });
        web.setDownloadListener((url,ua,cd,mime,length)->{if(local(url))exportDocument(url,"Campo document.pdf");});
        loading=new TextView(this);loading.setText("Campo Reader\n正在打开本机数据…");loading.setTextColor(Color.rgb(174,215,242));loading.setTextSize(19);loading.setGravity(Gravity.CENTER);loading.setBackgroundColor(Color.rgb(16,19,21));root.addView(loading,new FrameLayout.LayoutParams(-1,-1));loading.setOnClickListener(v->launch());
        getOnBackPressedDispatcher().addCallback(this,new OnBackPressedCallback(true){@Override public void handleOnBackPressed(){
            web.evaluateJavascript("(()=>{const d=document.querySelector('dialog[open]');if(d){d.close();return true}if(location.hash&&location.hash!=='#calendar'){document.getElementById('tab-calendar').click();return true}return false})()",handled->{if(!"true".equals(handled))moveTaskToBack(true);});
        }});
        launch();
    }
    private boolean local(String url){try{Uri u=Uri.parse(url);return app.runtime!=null&&"http".equals(u.getScheme())&&"127.0.0.1".equals(u.getHost())&&u.getPort()==Uri.parse(app.runtime.getString("origin")).getPort()&&u.getUserInfo()==null;}catch(Exception e){return false;}}
    private void launch(){loading.setVisibility(View.VISIBLE);app.ready.whenComplete((runtime,error)->runOnUiThread(()->{if(isFinishing())return;if(error!=null){loading.setText("Campo Reader 未能启动\n请关闭后重新打开应用");return;}try{web.loadUrl(runtime.getString("url"));}catch(Exception e){loading.setText("请重新打开应用。");}}));}
    private void openExternal(String url){if(!url.startsWith("https://"))return;try{startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(url)));}catch(ActivityNotFoundException e){toast("未找到浏览器。");}}
    private void toast(String s){runOnUiThread(()->Toast.makeText(this,s,Toast.LENGTH_SHORT).show());}
    public WebView getAppWebView(){return web;}
    public class MobileBridge {
        @JavascriptInterface public void exportPdf(String url,String title){if(local(url))runOnUiThread(()->exportDocument(url,title));}
        @JavascriptInterface public void about(){runOnUiThread(()->new AlertDialog.Builder(MainActivity.this).setTitle("Campo Reader "+BuildConfig.APP_VERSION).setMessage("自动更新在应用前台运行时进行。清除应用数据或卸载会删除账号和已保存的数据。\n\n此工具并非 FAU 官方应用。").setPositiveButton("知道了",null).setNeutralButton("项目页面",(d,i)->openExternal("https://github.com/vMarkEvanv/campo-reader")).show());}
    }
    private void exportDocument(String url,String title){
        if(!local(url))return;toast("正在准备 PDF…");app.worker.execute(()->{
            try{
                JSONObject info=new JSONObject(Python.getInstance().getModule("android_runtime").callAttr("export_document",url).toString());
                File folder=new File(getCacheDir(),"exports");folder.mkdirs();File out=new File(folder,"Campo-document.pdf");
                try(InputStream in=new FileInputStream(info.getString("path"));OutputStream stream=new FileOutputStream(out)){copy(in,stream);}
                runOnUiThread(()->{if(isFinishing())return;exportFile=out;exportTitle=info.optString("title","Campo document.pdf");new AlertDialog.Builder(this).setTitle(exportTitle).setItems(new String[]{"打开 / 预览","保存到文件"},(d,i)->{if(i==0)preview();else save();}).show();});
            }catch(Exception e){toast("PDF 暂时无法打开，归档仍保留在本机。");}
        });
    }
    private void preview(){try{Uri uri=FileProvider.getUriForFile(this,getPackageName()+".files",exportFile);startActivity(new Intent(Intent.ACTION_VIEW).setDataAndType(uri,"application/pdf").addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION));}catch(ActivityNotFoundException e){toast("未找到 PDF 阅读器，可以保存到文件后打开。");save();}}
    private void save(){try{startActivityForResult(new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/pdf").putExtra(Intent.EXTRA_TITLE,exportTitle),SAVE_PDF);}catch(ActivityNotFoundException e){toast("未找到文件管理器。");}}
    static void copy(InputStream in,OutputStream out)throws IOException{byte[] buffer=new byte[32768];int n;while((n=in.read(buffer))!=-1)out.write(buffer,0,n);}
    @Override protected void onActivityResult(int request,int result,Intent data){
        super.onActivityResult(request,result,data);
        if(request==PICK_PDF&&fileCallback!=null){Uri[] urls=null;if(result==RESULT_OK&&data!=null){if(data.getClipData()!=null){int n=Math.min(20,data.getClipData().getItemCount());urls=new Uri[n];for(int i=0;i<n;i++)urls[i]=data.getClipData().getItemAt(i).getUri();}else if(data.getData()!=null)urls=new Uri[]{data.getData()};}fileCallback.onReceiveValue(urls);fileCallback=null;}
        if(request==SAVE_PDF&&result==RESULT_OK&&data!=null&&data.getData()!=null&&exportFile!=null){Uri uri=data.getData();File file=exportFile;app.worker.execute(()->{try(InputStream in=new FileInputStream(file);OutputStream out=getContentResolver().openOutputStream(uri)){copy(in,out);toast("PDF 已保存。");}catch(Exception e){toast("未能保存 PDF，请重新选择位置。");}});}
    }
    @Override protected void onStart(){super.onStart();setForeground(true);}
    @Override protected void onStop(){setForeground(false);super.onStop();}
    private void setForeground(boolean value){app.ready.thenRun(()->app.worker.execute(()->Python.getInstance().getModule("android_runtime").callAttr("foreground",value)));}
    @Override protected void onDestroy(){if(fileCallback!=null){fileCallback.onReceiveValue(null);fileCallback=null;}if(web!=null){web.removeJavascriptInterface("CampoMobile");web.destroy();}super.onDestroy();}
}
