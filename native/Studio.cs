using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using System.Xml.Linq;
using Microsoft.Win32;
using WPath=System.Windows.Shapes.Path;
using Forms=System.Windows.Forms;

namespace RecoverX {
public partial class Studio:Window {
    public const string Light="#F4F3FC",Muted="#BCC0D3",Mint="#9FE5CF",Lilac="#C0B5FF",Panel="#1C1D2A",Line="#393A4C",Ink="#13151F";
    static Brush B(string c){return (Brush)new BrushConverter().ConvertFromString(c);}
    static readonly Dictionary<string,string> Paths=LoadIcons();
    static Stream Resource(string name){return typeof(Studio).Assembly.GetManifestResourceStream(name);}
    static Dictionary<string,string> LoadIcons(){using(var s=Resource("Icons.svg"))return XDocument.Load(s).Root.Elements().ToDictionary(x=>(string)x.Attribute("id"),x=>(string)x.Attribute("d"));}
    static new FrameworkElement Icon(string name,string color,int size){
        var canvas=new Canvas{Width=24,Height=24};
        canvas.Children.Add(new WPath{Data=Geometry.Parse(Paths[name]),Stroke=B(color),StrokeThickness=name=="brand"?0:1.7,
            Fill=name=="brand"?B(color):Brushes.Transparent,StrokeLineJoin=PenLineJoin.Round,StrokeStartLineCap=PenLineCap.Round,StrokeEndLineCap=PenLineCap.Round});
        return new Viewbox{Width=size,Height=size,Child=canvas};
    }
    static TextBlock T(string text,double size=14,string color=Light,bool bold=false){
        return new TextBlock{Text=text,FontSize=size,Foreground=B(color),FontWeight=bold?FontWeights.SemiBold:FontWeights.Normal,TextWrapping=TextWrapping.Wrap};
    }
    static Border Box(UIElement child,string color=Panel,int pad=18,string line=Line,int radius=13){
        return new Border{Background=B(color),BorderBrush=B(line),BorderThickness=new Thickness(1),CornerRadius=new CornerRadius(radius),Padding=new Thickness(pad),Child=child};
    }
    static Button Btn(string label,Action act,bool primary=false){
        var b=new Button{Content=label,VerticalAlignment=VerticalAlignment.Center};
        if(primary){b.Background=B("#C6BBFF");b.Foreground=B("#231D35");b.BorderBrush=B("#D4C9FF");}
        b.Click+=(o,e)=>act();AutomationProperties.SetName(b,label);return b;
    }
    static StackPanel Row(){return new StackPanel{Orientation=Orientation.Horizontal,VerticalAlignment=VerticalAlignment.Center};}
    static void Add(Panel parent,FrameworkElement child,double top=0,double left=0){
        child.Margin=new Thickness(left,top,0,0);parent.Children.Add(child);
    }
    static Grid Pair(UIElement left,UIElement right,bool autoRight=true){
        var grid=new Grid();grid.ColumnDefinitions.Add(new ColumnDefinition());grid.ColumnDefinitions.Add(new ColumnDefinition{Width=autoRight?GridLength.Auto:new GridLength(1,GridUnitType.Star)});
        grid.Children.Add(left);Grid.SetColumn(right,1);grid.Children.Add(right);return grid;
    }
    static StackPanel Labels(string name,string desc){
        var s=new StackPanel();Add(s,T(name,17,Light,true));Add(s,T(desc,13,Muted),4);return s;
    }
    Grid frame;StackPanel body,devicesBox;TextBlock foot;ScrollViewer scroll;
    List<UsbDisk> devices=new List<UsbDisk>();string inventoryError="";bool listing,closed;int generation;
    UsbDisk disk;string image,destination,caseDir,method="smart";int sector=512;
    object known;string knownTitle;bool sample,authorized;string screen;CancellationTokenSource active;
    Report report;bool gallery=true;string filter="All";int page;Button exportButton;
    ProgressBar meter;TextBlock stageLabel,measureLabel,timeLabel;DispatcherTimer timer;Stopwatch elapsed;
    public Studio(){
        Title="RecoverX  ·  Recovery Studio";Width=1080;Height=790;MinWidth=790;MinHeight=560;
        WindowStartupLocation=WindowStartupLocation.CenterScreen;FontFamily=new FontFamily("Segoe UI");
        Background=B(Ink);Foreground=B(Light);UseLayoutRounding=true;
        using(var s=Resource("Theme.xaml"))Resources.MergedDictionaries.Add((ResourceDictionary)XamlReader.Load(s));
        frame=new Grid{Background=B(Ink)};frame.RowDefinitions.Add(new RowDefinition{Height=GridLength.Auto});frame.RowDefinitions.Add(new RowDefinition());frame.RowDefinitions.Add(new RowDefinition{Height=GridLength.Auto});Content=frame;
        var brand=Row();brand.Children.Add(Box(Icon("brand","#241F38",28),Lilac,4,Lilac,9));Add(brand,T("RecoverX",24,Light,true),0,11);
        var divider=new Border{Width=1,Height=22,Background=B(Line)};Add(brand,divider,0,18);Add(brand,T("Recovery Studio",14,Muted),0,16);
        var sign=Row();sign.Children.Add(Icon("shield",Mint,17));Add(sign,T("Local recovery",13,Mint,true),0,8);
        var head=new Border{Background=B("#191A25"),BorderBrush=B(Line),BorderThickness=new Thickness(0,0,0,1),Padding=new Thickness(34,15,34,15),Child=Pair(brand,sign)};
        frame.Children.Add(head);
        scroll=new ScrollViewer{VerticalScrollBarVisibility=ScrollBarVisibility.Auto,HorizontalScrollBarVisibility=ScrollBarVisibility.Disabled};
        Grid.SetRow(scroll,1);frame.Children.Add(scroll);
        foot=T("Workspace",12,Muted);var bottom=Pair(foot,T("RecoverX   /   1.0 RC1",12,Muted));
        var footer=new Border{BorderBrush=B(Line),BorderThickness=new Thickness(0,1,0,0),Padding=new Thickness(34,9,34,10),Child=bottom};
        Grid.SetRow(footer,2);frame.Children.Add(footer);
        destination=Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
        Home();
        Loaded+=async(o,e)=>await Refresh(false);
        SourceInitialized+=(o,e)=>{var source=HwndSource.FromHwnd(new WindowInteropHelper(this).Handle);source.AddHook(DeviceChange);};
        Closing+=(o,e)=>{if(active!=null){e.Cancel=true;active.Cancel();if(stageLabel!=null)stageLabel.Text="Stopping safely…";}else closed=true;};
    }
    DispatcherTimer deviceTimer;
    IntPtr DeviceChange(IntPtr h,int msg,IntPtr wp,IntPtr lp,ref bool handled){
        if(msg==0x219 && (screen=="home"||screen=="devices")){
            if(deviceTimer==null){
                deviceTimer=new DispatcherTimer{Interval=TimeSpan.FromMilliseconds(700)};
                deviceTimer.Tick+=async(o,e)=>{deviceTimer.Stop();if(!closed&&(screen=="home"||screen=="devices"))await Refresh(false);};
            }
            deviceTimer.Stop();deviceTimer.Start();
        }
        return IntPtr.Zero;
    }
    void Page(string key,string location){
        screen=key;foot.Text=location;body=new StackPanel{Margin=new Thickness(34,23,34,22),MaxWidth=1280};
        scroll.Content=body;scroll.ScrollToTop();
        var fade=new DoubleAnimation(.7,1,new Duration(TimeSpan.FromMilliseconds(140)));
        if(SystemParameters.ClientAreaAnimation)body.BeginAnimation(OpacityProperty,fade);
    }
    void Section(string title,UIElement control=null){
        var label=T(title,21,Light,true);label.VerticalAlignment=VerticalAlignment.Center;
        Add(body,control==null?(FrameworkElement)label:Pair(label,control),20);
    }
    void Heading(string state,string title,string detail){
        Add(body,T(state.ToUpperInvariant(),12,Lilac,true));
        Add(body,T(title,35,Light,true),5);Add(body,T(detail,15,Muted),5);
    }
    void Home(){
        Page("home","Workspace  /  Overview");
        var copy=new StackPanel{VerticalAlignment=VerticalAlignment.Center};
        Add(copy,T("USB RECOVERY",12,"#B9ADF1",true));
        Add(copy,T("Recover deleted files",36,Light,true),8);
        Add(copy,T("Connect a USB drive to find and preview lost files.",15,"#D8D6E8"),8);
        var ctl=Btn("Select a USB drive   →",()=>{DevicePage();},true);ctl.HorizontalAlignment=HorizontalAlignment.Left;Add(copy,ctl,19);
        FrameworkElement art;using(var s=Resource("Hero.xaml"))art=(FrameworkElement)XamlReader.Load(s);
        var hero=Pair(copy,art,false);hero.ColumnDefinitions[0].Width=new GridLength(1.16,GridUnitType.Star);hero.ColumnDefinitions[1].Width=new GridLength(1,GridUnitType.Star);
        var plate=Box(hero,"#25253D",24,"#575271",18);
        plate.Background=new LinearGradientBrush((Color)ColorConverter.ConvertFromString("#29273D"),(Color)ColorConverter.ConvertFromString("#30364F"),14);
        plate.Height=222;Add(body,plate);
        DeviceArea();Section("Other sources");
        var imageBtn=Tile("drive","Disk image","Open an existing raw image",Lilac,ChooseImage);
        var demoBtn=Tile("layers","Validation sample","Try three known deleted files",Mint,Sample);
        demoBtn.Margin=new Thickness(12,0,0,0);Add(body,Pair(imageBtn,demoBtn,false),10);
    }
    Button Tile(string glyph,string title,string note,string accent,Action action){
        var row=new Grid();row.ColumnDefinitions.Add(new ColumnDefinition{Width=GridLength.Auto});row.ColumnDefinitions.Add(new ColumnDefinition());row.ColumnDefinitions.Add(new ColumnDefinition{Width=GridLength.Auto});
        var symbol=Box(Icon(glyph,accent,22),"#292A3C",9,"#444459",10);symbol.VerticalAlignment=VerticalAlignment.Center;row.Children.Add(symbol);
        var labels=Labels(title,note);labels.Margin=new Thickness(13,0,8,0);Grid.SetColumn(labels,1);row.Children.Add(labels);
        var chevron=T("›",23,Muted);chevron.VerticalAlignment=VerticalAlignment.Center;Grid.SetColumn(chevron,2);row.Children.Add(chevron);
        var b=Btn(title,action);b.Content=row;b.Background=B(Panel);b.Padding=new Thickness(15);b.HorizontalContentAlignment=HorizontalAlignment.Stretch;
        return b;
    }
    async void DevicePage(){
        Page("devices","Workspace  /  USB devices");Back(Home);
        Heading("Source","Select a USB drive","Choose the physical device you want to read.");DeviceArea();
        if(!listing&&devices.Count==0&&inventoryError=="")await Refresh(false);
    }
    void Back(Action action){var b=Btn("‹  Back",action);b.HorizontalAlignment=HorizontalAlignment.Left;b.Margin=new Thickness(0,0,0,18);body.Children.Add(b);}
    void DeviceArea(){
        var refresh=Btn("↻   Refresh",async()=>await Refresh(false));Section("Connected USB drives",refresh);
        devicesBox=new StackPanel();Add(body,devicesBox,10);DeviceCards();
    }
    void DeviceCards(){
        if(devicesBox==null||(screen!="home"&&screen!="devices"))return;
        devicesBox.Children.Clear();
        if(listing){var s=Labels("Looking for USB drives…","Reading Windows storage information");var progress=new ProgressBar{IsIndeterminate=true,Height=3,Margin=new Thickness(0,12,0,0)};s.Children.Add(progress);Add(devicesBox,Box(s));return;}
        if(inventoryError.Length>0){
            var s=Labels("USB discovery needs attention","Allow Windows storage access to check connected drives.");
            var row=Pair(s,Btn("Check USB access",async()=>await Refresh(true)));
            var box=Box(row);box.ToolTip=inventoryError;Add(devicesBox,box);return;
        }
        if(devices.Count==0){var row=Row();row.Children.Add(Icon("usb",Lilac,30));Add(row,Labels("Waiting for a USB drive","Connect a drive, then select it here."),0,16);Add(devicesBox,Box(row));return;}
        foreach(var d in devices){var device=d;Add(devicesBox,Tile("usb",device.Name,Format.Size(device.Size)+"   ·   "+device.Volumes+"   ·   Disk "+device.Number,Mint,()=>SelectSource(device,null,false)),4);}
    }
    static List<UsbDisk> DiscoverLocally(){
        try{return Storage.Discover();}
        catch(UnauthorizedAccessException){if(Presence.AnyUsb()==false)return new List<UsbDisk>();throw;}
        catch(System.Management.ManagementException){if(Presence.AnyUsb()==false)return new List<UsbDisk>();throw;}
    }
    async Task Refresh(bool elevate){
        if(listing)return;listing=true;DeviceCards();int mine=++generation;
        try{
            var found=await Task.Run(()=>elevate?Broker.Call(new Request{op="list"},CancellationToken.None,(json,stream)=>Json.Read<List<UsbDisk>>(json)):DiscoverLocally());
            if(mine==generation){devices=found;inventoryError="";}
        }catch(Exception e){devices.Clear();inventoryError=e.Message;if(elevate&&!closed)MessageBox.Show(this,e.Message,"USB discovery",MessageBoxButton.OK,MessageBoxImage.Information);}
        finally{listing=false;if(!closed)DeviceCards();}
    }
    void ChooseImage(){
        var open=new OpenFileDialog{Title="Select a raw disk image",Filter="Raw disk images|*.img;*.dd;*.raw;*.bin"};
        if(open.ShowDialog(this)==true)SelectSource(null,open.FileName,false);
    }
    public void Sample(){SelectSource(null,Path.Combine(Session.Root,@"validation\sample\three-deleted.img"),true);}
    void SelectSource(UsbDisk source,string file,bool isSample){
        disk=source;image=file;sample=isSample;sector=disk==null?512:disk.Sector;method="smart";authorized=false;known=null;knownTitle=null;caseDir=null;
        if(sample){known=Json.Read<object>(File.ReadAllText(Path.Combine(Session.Root,@"validation\sample\original-hashes.json")));knownTitle="Three sample originals";}
        Methods();
    }
    string SourceTitle{get{return disk!=null?disk.Name+(String.IsNullOrEmpty(disk.Volumes)?"":" · "+disk.Volumes):(sample?"Deleted-file validation sample":Path.GetFileName(image));}}
    static readonly string[][] MethodsList={new[]{"smart","spark","Smart recovery","Choose an engine from the file records.",Lilac},new[]{"tsk","folder","File records","Restore names and folders with TSK.",Mint},
        new[]{"photorec","scan","Signature scan","Find recognizable content with PhotoRec.","#A5C9FF"},new[]{"combined","layers","Both engines","Run both methods and group matching files.","#EDBBD5"}};
    public void Methods(){
        Page("methods","Workspace  /  Recovery method");Back(Home);Heading("Recovery method","Choose how to search",SourceTitle);
        var grid=new UniformGrid{Columns=2};foreach(var option in MethodsList){
            var opt=option;bool selected=opt[0]==method;var btn=Tile(opt[1],opt[2]+(selected?"   ✓":""),opt[3],opt[4],()=>{method=opt[0];Methods();});
            btn.BorderBrush=B(selected?Lilac:Line);btn.Background=B(selected?"#302B46":Panel);btn.Margin=new Thickness(0,0,10,10);grid.Children.Add(btn);
        }Add(body,grid,20);
        var adv=new StackPanel();var selectors=Row();
        Add(selectors,Btn("CART only"+(method=="cart"?"  ✓":""),()=>{method="cart";Methods();}));
        Add(selectors,Btn("Rule-v1 only"+(method=="rule"?"  ✓":""),()=>{method="rule";Methods();}),0,8);
        Add(adv,selectors,8);
        if(disk==null&&!sample){var sizes=Row();Add(sizes,T("Image sector size",13,Muted));var combo=new ComboBox{ItemsSource=new[]{512,1024,2048,4096},SelectedItem=sector,MinWidth=90};combo.SelectionChanged+=(o,e)=>sector=(int)combo.SelectedItem;Add(sizes,combo,0,12);Add(adv,sizes,8);}
        Add(adv,Btn(knownTitle??"Load original SHA-256 manifest",ChooseKnown),8);
        var exp=new Expander{Header="Advanced settings",Content=adv,IsExpanded=method=="cart"||method=="rule"};Add(body,exp,3);
        Section("Save recovery to",Btn("Choose folder",ChooseFolder));Add(body,T(destination,14,Muted),6);
        var desc=disk==null?"I confirm this image and destination.":"I confirm USB disk "+disk.Number+" ("+Format.Size(disk.Size)+") and this separate destination.";
        var check=new CheckBox{Content=new TextBlock{Text=desc,TextWrapping=TextWrapping.Wrap,Foreground=B(Light)},IsChecked=authorized};
        var start=Btn("Start recovery   →",async()=>await Start(),true);start.IsEnabled=authorized;
        check.Checked+=(o,e)=>{authorized=true;start.IsEnabled=true;};check.Unchecked+=(o,e)=>{authorized=false;start.IsEnabled=false;};
        Add(body,check,18);start.HorizontalAlignment=HorizontalAlignment.Left;Add(body,start,15);
    }
    void ChooseFolder(){
        using(var pick=new Forms.FolderBrowserDialog{Description="Choose an existing folder on the destination disk",SelectedPath=destination,ShowNewFolderButton=false})
            if(pick.ShowDialog()==Forms.DialogResult.OK){destination=pick.SelectedPath;authorized=false;Methods();}
    }
    void ChooseKnown(){
        var open=new OpenFileDialog{Title="Original hashes",Filter="RecoverX hash manifest|*.json"};
        if(open.ShowDialog(this)!=true)return;
        try{var file=new FileInfo(open.FileName);if(file.Length>8*1024*1024)throw new IOException("Manifest is too large.");
            var data=Json.Read<ReferenceSet>(File.ReadAllText(file.FullName));
            if(data.deleted==null||data.deleted.Count==0||data.deleted.Any(i=>i==null||String.IsNullOrWhiteSpace(i.id)||i.sha256==null||!System.Text.RegularExpressions.Regex.IsMatch(i.sha256,"^[a-fA-F0-9]{64}$")))throw new IOException("A manifest needs deleted entries with id and sha256 fields.");
            foreach(var item in data.deleted)item.sha256=item.sha256.ToLowerInvariant();known=data;knownTitle=file.Name;Methods();
        }catch(Exception ex){MessageBox.Show(this,ex.Message,"Hash manifest");}
    }
    public class RefFile{public string id{get;set;}public string sha256{get;set;}}
    public class ReferenceSet{public List<RefFile> deleted{get;set;}}
    void ProgressPage(string title){
        Page("progress","Workspace  /  Active session");Heading("Active session",title,SourceTitle);
        var card=new StackPanel();var head=Row();head.Children.Add(Icon("scan",Mint,32));stageLabel=T("Preparing the session",20,Light,true);Add(head,stageLabel,0,14);Add(card,head);
        meter=new ProgressBar{Minimum=0,Maximum=100,Height=7,IsIndeterminate=true,Foreground=B(Lilac),Background=B("#37364B")};Add(card,meter,24);
        measureLabel=T("Starting…",13,Muted);timeLabel=T("00:00",13,Mint,true);Add(card,Pair(measureLabel,timeLabel),12);Add(body,Box(card,Panel,24),26);
        var cancel=Btn("Cancel",()=>{if(active!=null){active.Cancel();stageLabel.Text="Stopping safely…";}});cancel.HorizontalAlignment=HorizontalAlignment.Left;Add(body,cancel,18);
        elapsed=Stopwatch.StartNew();timer=new DispatcherTimer{Interval=TimeSpan.FromSeconds(1)};timer.Tick+=(o,e)=>{timeLabel.Text=elapsed.Elapsed.ToString(@"hh\:mm\:ss");};timer.Start();
    }
    void Notify(string text,long done,long total){
        Dispatcher.Invoke(()=>{if(screen!="progress"||active==null)return;stageLabel.Text=active.IsCancellationRequested?"Stopping safely…":text;
            meter.IsIndeterminate=total==0;
            if(total>0){meter.Value=100.0*done/total;measureLabel.Text=text.StartsWith("Verifying exported")?done+" of "+total+" files":Format.Size(done)+" of "+Format.Size(total)+"   ·   "+meter.Value.ToString("0")+"%";}
            else measureLabel.Text="Working · elapsed time shown at right";});
    }
    async Task Start(){
        if(!authorized||active!=null)return;active=new CancellationTokenSource();var token=active.Token;authorized=false;ProgressPage("Recovery in progress");
        try{report=await Task.Run(()=>{
                caseDir=Acquisition.Acquire(destination,disk,image,sector,method,token,Notify,p=>caseDir=p);
                return Session.Scan(caseDir,method,sector,known,token,Notify);
            });
            foreach(var f in report.files)f.Selected=true;filter="All";page=0;gallery=true;Results();
        }catch(Exception e){Problem(token.IsCancellationRequested?"Recovery cancelled":"Recovery stopped",token.IsCancellationRequested?"The current operation stopped. A partial image cannot be used as a completed capture.":
                    (e is Win32Exception && ((Win32Exception)e).NativeErrorCode==1223?"Administrator access was declined. No USB image was acquired.":e.Message));}
        finally{timer.Stop();active.Dispose();active=null;}
    }
    void Problem(string title,string message){
        Page("problem","Workspace  /  Session status");Heading("Session status",title,message);
        if(caseDir!=null&&Directory.Exists(caseDir)){Section("Case folder");Add(body,T(caseDir,14,Muted),5);Add(body,Btn("Open case folder",()=>OpenFolder(caseDir)),12);}
        var back=Btn("Return to workspace",Home,true);back.HorizontalAlignment=HorizontalAlignment.Left;Add(body,back,18);
    }
    static void OpenFolder(string folder){Process.Start(new ProcessStartInfo("explorer.exe","\""+folder+"\""){UseShellExecute=false});}
}
}
