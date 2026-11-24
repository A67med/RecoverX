using RecoverX;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;

public static class DesktopChecks {
    static int passed; static List<string> records=new List<string>();static string dir;
    static void Check(bool value,string label){if(!value)throw new Exception(label);records.Add("PASS "+label);Console.WriteLine(records.Last());passed++;}
    static void Reject(Action run,string label){try{run();}catch(Exception){Check(true,label);return;}throw new Exception("Expected rejection: "+label);}
    static object Field(Studio w,string name){return typeof(Studio).GetField(name,BindingFlags.Instance|BindingFlags.NonPublic).GetValue(w);}
    static IEnumerable<T> Children<T>(DependencyObject root) where T:DependencyObject {
        for(int i=0;i<VisualTreeHelper.GetChildrenCount(root);i++){var child=VisualTreeHelper.GetChild(root,i);if(child is T)yield return (T)child;foreach(var c in Children<T>(child))yield return c;}
    }
    static Button Button(Studio w,string name){w.UpdateLayout();return Children<Button>(w).First(b=>AutomationProperties.GetName(b).StartsWith(name));}
    static void Click(Button button){if(!button.IsEnabled)throw new Exception("Disabled action");button.RaiseEvent(new RoutedEventArgs(System.Windows.Controls.Button.ClickEvent));}
    static async Task Wait(Func<bool> condition,string label){for(int i=0;i<500&&!condition();i++)await Task.Delay(100);Check(condition(),label);}
    static async Task Shot(Studio w,string name){
        await Task.Delay(250);w.UpdateLayout();var root=(FrameworkElement)w.Content;
        int width=(int)root.ActualWidth,height=(int)root.ActualHeight;var bmp=new RenderTargetBitmap(width,height,96,96,PixelFormats.Pbgra32);bmp.Render(root);
        var png=new PngBitmapEncoder();png.Frames.Add(BitmapFrame.Create(bmp));using(var f=File.Create(Path.Combine(dir,name+".png")))png.Save(f);
    }
    static void Guards(){
        Check(Storage.Eligible(7,false,false,false,8192,4096),"Accept a 4Kn non-system USB candidate");
        Check(!Storage.Eligible(7,null,false,false,8192,512),"Reject unknown boot status");Check(!Storage.Eligible(7,true,false,false,8192,512),"Reject boot USB");
        Check(!Storage.Eligible(7,false,true,false,8192,512),"Reject system USB");Check(!Storage.Eligible(17,false,false,false,8192,512),"Reject NVMe source");
        Check(!Storage.Eligible(7,false,false,true,8192,512),"Reject offline USB");
        Reject(()=>Storage.ValidateDisks(1,1,0,17),"Reject different drive letters on the same source disk");
        Reject(()=>Storage.ValidateDisks(0,1,0,17),"Reject system disk by physical number");
        Reject(()=>Storage.ValidateDisks(2,3,0,15),"Reject file-backed virtual output");
        Storage.ValidateDisks(2,0,0,17);Check(true,"Accept separate NVMe destination");
        byte[] data=Enumerable.Range(0,1200000).Select(i=>(byte)(i%251)).ToArray();
        var read=new MemoryStream(data,false);var output=new MemoryStream();string hash=Acquisition.CopyExact(read,output,data.Length,CancellationToken.None,(a,b)=>{});
        Check(output.ToArray().SequenceEqual(data)&&hash.Length==64,"Acquire bytes from a read-only mock source");
        Reject(()=>Acquisition.CopyExact(new MemoryStream(data,false),new MemoryStream(),data.Length+1,CancellationToken.None,(a,b)=>{}),"Reject truncated acquisition");
        var cancel=new CancellationTokenSource();cancel.Cancel();
        Reject(()=>Acquisition.CopyExact(new MemoryStream(data,false),new MemoryStream(),data.Length,cancel.Token,(a,b)=>{}),"Cancel acquisition before writing");
    }
    static async Task Flow(Studio w){
        await Wait(()=>!(bool)Field(w,"listing"),"Windows USB discovery returned a list or an explicit error");
        string inventory=(string)Field(w,"inventoryError");
        records.Add("Windows storage inventory: "+(inventory.Length>0?inventory:((List<UsbDisk>)Field(w,"devices")).Count+" eligible USB disks"));
        await Shot(w,"01-workspace");
        Click(Button(w,"Validation sample"));w.UpdateLayout();
        Check(!Button(w,"Start recovery").IsEnabled,"Require source confirmation");
        Click(Button(w,"Both engines"));await Shot(w,"02-methods");
        typeof(Studio).GetField("destination",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(w,dir);
        Children<CheckBox>(w).First().IsChecked=true;Click(Button(w,"Start recovery"));
        await Wait(()=>(string)Field(w,"screen")=="results"||(string)Field(w,"screen")=="problem","Desktop scan returned a result");
        Check((string)Field(w,"screen")=="results","Completed the normal desktop image workflow");
        var report=(Report)Field(w,"report");Check(report.files.Count==3 && report.metrics.exact_recovered==3 && report.metrics.outputs==6,"Both engines recovered all three original hashes");
        await Shot(w,"03-results");Click(Button(w,"Deselect all"));Check(!Button(w,"Recover selected").IsEnabled,"Deselect all disables export");
        Click(Button(w,"Select all"));Click(Button(w,"List view"));Check(Button(w,"Gallery").IsEnabled,"Switch between list and gallery");
        var combo=Children<ComboBox>(w).First();combo.SelectedItem="Images";w.UpdateLayout();
        Check(Children<CheckBox>(w).Count()==2,"Image filter contains two files");
        Click(Button(w,"Recover selected"));await Wait(()=>(string)Field(w,"screen")=="done"||(string)Field(w,"screen")=="problem","Export operation returned");
        Check((string)Field(w,"screen")=="done","Completed verified export");
        var caseDir=(string)Field(w,"caseDir");var receipt=Directory.GetFiles(caseDir,"export-receipt.json",SearchOption.AllDirectories).Single();
        var exported=Json.Read<ExportReceipt>(File.ReadAllText(receipt));Check(exported.verified.Count==3 && exported.failed.Count==0,"Export receipt records three verified files");
        await Shot(w,"04-export");
        var bad=report.files[0];bad.sha256=new string('0',64);
        var fail=Session.Export(caseDir,null,new List<Asset>{bad},CancellationToken.None,(s,a,b)=>{});
        Check(fail.verified.Count==0&&fail.failed.Count==1,"Changed content never publishes a verified export");
    }
    [STAThread] public static int Main(string[] args){
        dir=Path.GetFullPath(args.Length==0?Path.Combine(Path.GetTempPath(),"RecoverX-QA-"+Guid.NewGuid().ToString("N")):args[0]);
        Directory.CreateDirectory(dir);Console.WriteLine(dir);int rc=0;
        try{
            Guards();System.Windows.Media.RenderOptions.ProcessRenderMode=System.Windows.Interop.RenderMode.SoftwareOnly;
            var app=new Application();var w=new Studio{ShowInTaskbar=false,ShowActivated=false,WindowStartupLocation=WindowStartupLocation.Manual,Left=-14000,Top=-14000};
            w.Loaded+=async(o,e)=>{try{await Flow(w);}catch(Exception ex){records.Add("FAIL "+ex);Console.WriteLine(ex);rc=1;}finally{app.Shutdown();}};
            app.Run(w);
        }catch(Exception e){Console.WriteLine(e);records.Add("FAIL "+e);rc=1;}
        records.Add(passed+" checks passed; exit "+rc);File.WriteAllLines(Path.Combine(dir,"desktop-checks.txt"),records);return rc;
    }
}


