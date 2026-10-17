package io.github.vmarkevanv.camporeader;

import android.app.AlertDialog;
import android.content.*;
import android.content.pm.*;
import android.net.Uri;
import android.provider.Settings;
import android.widget.Toast;
import androidx.core.content.FileProvider;
import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;

/** Optional GitHub APK updates. No account, credentials or device identifiers are sent. */
final class AndroidUpdater {
    static final int INSTALL_PERMISSION=204;
    static final String REPO="https://github.com/vMarkEvanv/campo-reader/";
    final MainActivity activity;
    final ExecutorService network=Executors.newSingleThreadExecutor();
    boolean checking=false,downloading=false;
    File pending;
    AndroidUpdater(MainActivity activity){this.activity=activity;}
    static int compare(String a,String b){
        if(!a.matches("[0-9]+\\.[0-9]+\\.[0-9]+")||!b.matches("[0-9]+\\.[0-9]+\\.[0-9]+"))throw new IllegalArgumentException();
        String[] x=a.split("\\."),y=b.split("\\.");for(int i=0;i<3;i++){int c=Integer.compare(Integer.parseInt(x[i]),Integer.parseInt(y[i]));if(c!=0)return c;}return 0;
    }
    static JSONObject candidate(JSONArray releases,String current)throws Exception{
        JSONObject best=null;
        for(int i=0;i<releases.length();i++){
            JSONObject release=releases.getJSONObject(i);String tag=release.optString("tag_name");
            if(release.optBoolean("draft")||!tag.matches("android-v[0-9]+\\.[0-9]+\\.[0-9]+"))continue;
            String version=tag.substring(9);if(compare(version,current)<=0||best!=null&&compare(version,best.getString("version"))<=0)continue;
            String apk="",sums="";JSONArray assets=release.optJSONArray("assets");if(assets==null)continue;
            String prefix=REPO+"releases/download/"+tag+"/",filename="CampoReader-Android-"+version+".apk";
            for(int j=0;j<assets.length();j++){JSONObject asset=assets.getJSONObject(j);String name=asset.optString("name"),url=asset.optString("browser_download_url");
                if(name.equals(filename)&&url.equals(prefix+filename))apk=url;
                if(name.equals("SHA256SUMS.txt")&&url.equals(prefix+"SHA256SUMS.txt"))sums=url;
            }
            if(!apk.isEmpty()&&!sums.isEmpty())best=new JSONObject().put("version",version).put("apk",apk).put("sums",sums).put("filename",filename).put("body",release.optString("body"));
        }return best;
    }
    void ui(Runnable task){activity.runOnUiThread(()->{if(!activity.isFinishing()&&!activity.isDestroyed())task.run();});}
    void toast(String text){ui(()->Toast.makeText(activity,text,Toast.LENGTH_LONG).show());}
    void check(boolean manual){
        if(checking){if(manual)toast("正在检查更新…");return;}checking=true;if(manual)toast("正在检查更新…");
        network.execute(()->{try{
            JSONObject latest=null;
            for(int page=1;page<=3;page++){
                JSONArray list=new JSONArray(new String(read("https://api.github.com/repos/vMarkEvanv/campo-reader/releases?per_page=100&page="+page,2*1024*1024),StandardCharsets.UTF_8));
                JSONObject item=candidate(list,BuildConfig.APP_VERSION);
                if(item!=null&&(latest==null||compare(item.getString("version"),latest.getString("version"))>0))latest=item;
                if(list.length()<100)break;
            }
            if(latest==null){if(manual)toast("当前已是最新版本。");return;}
            JSONObject release=latest;
            ui(()->{String notes=release.optString("body");if(notes.length()>2500)notes=notes.substring(0,2500)+"…";
                new AlertDialog.Builder(activity).setTitle("发现新版本 "+release.optString("version")).setMessage(notes+"\n\n下载后由你确认安装，账号和数据会保留。").setNegativeButton("暂不更新",null).setPositiveButton("下载更新",(d,i)->download(release)).show();});
        }catch(Exception e){if(manual)toast("暂时无法检查更新，请检查网络后重试。");}finally{ui(()->checking=false);}});
    }
    static boolean trusted(String url){try{URI u=new URI(url);String h=u.getHost();return "https".equals(u.getScheme())&&u.getUserInfo()==null&&(u.getPort()==-1||u.getPort()==443)&&(h!=null&&(h.equals("github.com")||h.equals("api.github.com")||h.equals("release-assets.githubusercontent.com")||h.equals("objects.githubusercontent.com")));}catch(Exception e){return false;}}
    static InputStream open(String url)throws Exception{
        for(int i=0;i<6;i++){
            if(!trusted(url))throw new SecurityException();
            HttpURLConnection c=(HttpURLConnection)new URL(url).openConnection();c.setConnectTimeout(15000);c.setReadTimeout(30000);c.setInstanceFollowRedirects(false);c.setRequestProperty("User-Agent","CampoReader-Android");c.setRequestProperty("Accept","application/vnd.github+json");
            int status=c.getResponseCode();if(status>=300&&status<400){String next=c.getHeaderField("Location");c.disconnect();if(next==null)throw new IOException();url=new URL(new URL(url),next).toString();continue;}
            if(status!=200){c.disconnect();throw new IOException("HTTP "+status);}
            InputStream in=c.getInputStream();return new FilterInputStream(in){@Override public void close()throws IOException{try{super.close();}finally{c.disconnect();}}};
        }throw new IOException("Too many redirects");
    }
    static byte[] read(String url,int limit)throws Exception{try(InputStream in=open(url);ByteArrayOutputStream out=new ByteArrayOutputStream()){byte[] buffer=new byte[32768];int n;while((n=in.read(buffer))!=-1){if(out.size()+n>limit)throw new IOException("Too large");out.write(buffer,0,n);}return out.toByteArray();}}
    void download(JSONObject release){
        if(downloading){toast("更新正在下载。");return;}downloading=true;
        AlertDialog progress=new AlertDialog.Builder(activity).setTitle("正在下载更新").setMessage("下载完成后可选择安装，你可以继续使用应用。").setPositiveButton("后台下载",null).show();
        network.execute(()->{File out=null;try{
            String sums=new String(read(release.getString("sums"),65536),StandardCharsets.UTF_8),expected="";
            for(String line:sums.split("\\r?\\n")){String[] parts=line.trim().split("\\s+",2);if(parts.length==2&&parts[0].matches("[a-fA-F0-9]{64}")&&parts[1].replaceFirst("^\\*","").equals(release.getString("filename")))expected=parts[0];}
            if(expected.isEmpty())throw new SecurityException();
            File dir=new File(activity.getCacheDir(),"updates");dir.mkdirs();out=new File(dir,"CampoReader-update.apk");MessageDigest digest=MessageDigest.getInstance("SHA-256");
            try(InputStream in=open(release.getString("apk"));OutputStream stream=new FileOutputStream(out)){
                byte[] buffer=new byte[65536];int n;long size=0,last=0;while((n=in.read(buffer))!=-1){size+=n;if(size>160*1024*1024)throw new IOException();stream.write(buffer,0,n);digest.update(buffer,0,n);if(size-last>1024*1024){last=size;final long count=size;ui(()->progress.setMessage("已下载 "+count/1024/1024+" MB · 可继续使用应用"));}}
            }
            StringBuilder hex=new StringBuilder();for(byte b:digest.digest())hex.append(String.format(Locale.ROOT,"%02x",b&255));if(!expected.equalsIgnoreCase(hex.toString()))throw new SecurityException();
            verify(out,release.getString("version"));pending=out;
            ui(()->{progress.dismiss();new AlertDialog.Builder(activity).setTitle("更新已准备好").setMessage("安装新版会保留现有数据。").setNegativeButton("稍后",null).setPositiveButton("安装",(d,i)->install()).show();});
        }catch(Exception e){if(out!=null)out.delete();ui(progress::dismiss);toast("更新下载或校验失败，请稍后重新检查更新。");}finally{ui(()->downloading=false);}});
    }
    void verify(File file,String version)throws Exception{
        PackageManager pm=activity.getPackageManager();int flags=android.os.Build.VERSION.SDK_INT>=28?PackageManager.GET_SIGNING_CERTIFICATES:PackageManager.GET_SIGNATURES;
        PackageInfo apk=pm.getPackageArchiveInfo(file.getAbsolutePath(),flags),installed=pm.getPackageInfo(activity.getPackageName(),flags);
        if(apk==null||!activity.getPackageName().equals(apk.packageName)||!version.equals(apk.versionName))throw new SecurityException();
        long code=android.os.Build.VERSION.SDK_INT>=28?apk.getLongVersionCode():apk.versionCode,current=android.os.Build.VERSION.SDK_INT>=28?installed.getLongVersionCode():installed.versionCode;
        if(code<=current)throw new SecurityException();
        Signature[] expected,actual;
        if(android.os.Build.VERSION.SDK_INT>=28){if(apk.signingInfo==null||installed.signingInfo==null)throw new SecurityException();expected=installed.signingInfo.getApkContentsSigners();actual=apk.signingInfo.getApkContentsSigners();}
        else{expected=installed.signatures;actual=apk.signatures;}
        if(expected==null||actual==null||expected.length==0||!new HashSet<>(Arrays.asList(expected)).equals(new HashSet<>(Arrays.asList(actual))))throw new SecurityException();
    }
    void install(){
        if(pending==null||!pending.isFile())return;
        if(!activity.getPackageManager().canRequestPackageInstalls()){
            new AlertDialog.Builder(activity).setTitle("允许安装应用更新").setMessage("请在系统设置中允许 Campo Reader 安装更新。返回后会再次询问是否安装。").setNegativeButton("取消",null).setPositiveButton("打开设置",(d,i)->{try{activity.startActivityForResult(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,Uri.parse("package:"+activity.getPackageName())),INSTALL_PERMISSION);}catch(ActivityNotFoundException e){toast("请在系统设置中允许安装应用。");}}).show();return;
        }
        try{Uri uri=FileProvider.getUriForFile(activity,activity.getPackageName()+".files",pending);activity.startActivity(new Intent(Intent.ACTION_VIEW).setDataAndType(uri,"application/vnd.android.package-archive").addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION));}catch(ActivityNotFoundException e){toast("未找到系统安装程序。");}
    }
    void resumeInstall(){if(pending!=null&&activity.getPackageManager().canRequestPackageInstalls())new AlertDialog.Builder(activity).setTitle("安装更新？").setMessage("现有账号与数据会保留。").setNegativeButton("稍后",null).setPositiveButton("安装",(d,i)->install()).show();}
}
