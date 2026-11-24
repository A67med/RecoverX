using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace RecoverX {
public partial class Studio{
    FrameworkElement Preview(Asset asset){
        if(asset.Group=="Images" && asset.size>0 && asset.size<=24*1024*1024 &&
           (asset.detected_type=="png"||asset.detected_type=="jpeg")){
            try{using(var stream=File.OpenRead(Session.AssetPath(caseDir,asset))){
                var decoder=BitmapDecoder.Create(stream,BitmapCreateOptions.DelayCreation,BitmapCacheOption.None);
                var frame=decoder.Frames[0];
                if((long)frame.PixelHeight*frame.PixelWidth>32000000 || frame.PixelWidth>16000 || frame.PixelHeight>16000)throw new IOException();
                stream.Position=0;var thumbnail=new BitmapImage();thumbnail.BeginInit();thumbnail.StreamSource=stream;thumbnail.DecodePixelWidth=248;
                thumbnail.CacheOption=BitmapCacheOption.OnLoad;thumbnail.EndInit();thumbnail.Freeze();
                return new Image{Source=thumbnail,Stretch=Stretch.UniformToFill,Height=100,ClipToBounds=true};
            }}catch(Exception){}
        }
        var s=new StackPanel{HorizontalAlignment=HorizontalAlignment.Center,VerticalAlignment=VerticalAlignment.Center};
        Add(s,Icon(asset.Group=="Images"?"image":asset.Group=="Documents"?"doc":"layers",asset.Group=="Documents"?"#EDC3CF":Lilac,30));
        var text=T(Path.GetExtension(asset.name).TrimStart('.').ToUpperInvariant(),11,Muted,true);text.HorizontalAlignment=HorizontalAlignment.Center;Add(s,text,4);
        return new Border{Height=100,Background=B("#29293A"),Child=s};
    }
    void Selection(){if(exportButton!=null){int count=report.files.Count(f=>f.Selected);exportButton.Content="Recover selected  ("+count+")   →";exportButton.IsEnabled=count>0;}}
    void Results(){
        Page("results","Workspace  /  Scan results");
        string title=report.status=="completed"?"Review recovered files":report.status=="cancelled"?"Scan cancelled":report.status=="failed"?"Scan failed":"Review partial results";
        Heading("Scan results",title,SourceTitle);
        var stats=new UniformGrid{Columns=3};
        foreach(var pair in new[]{new[]{report.files.Count.ToString(),"Distinct files"},new[]{Format.Size(report.files.Sum(f=>f.size)),"Candidate data"},
              new[]{report.metrics.ground_truth?report.metrics.exact_recovered.ToString():report.seconds.ToString("0.0")+" s",report.metrics.ground_truth?"Original hashes matched":"Scan time"}}){
            var s=new StackPanel();Add(s,T(pair[0],25,Light,true));Add(s,T(pair[1],12,Muted),3);var box=Box(s,Panel,12);box.Margin=new Thickness(0,0,8,0);stats.Children.Add(box);
        }Add(body,stats,17);
        if(report.warnings.Count>0)Add(body,T(String.Join("\n",report.warnings),13,"#F0C5A6"),10);
        var filters=Row();var kinds=new[]{"All","Images","Documents","Video","Audio","Other"}.Where(k=>k=="All"||report.files.Any(f=>f.Group==k)).ToArray();
        var pick=new ComboBox{ItemsSource=kinds,SelectedItem=filter,MinWidth=115,Margin=new Thickness(7,0,0,0)};Add(filters,T("File type",13,Muted));filters.Children.Add(pick);
        pick.SelectionChanged+=(o,e)=>{if(pick.SelectedItem!=null){filter=(string)pick.SelectedItem;page=0;Results();}};
        var actions=Row();var select=Btn("Select all",()=>{foreach(var a in Filtered())a.Selected=true;Results();});
        var clear=Btn("Deselect all",()=>{foreach(var a in Filtered())a.Selected=false;Results();});
        Add(actions,select);Add(actions,clear,0,5);Add(actions,Btn(gallery?"List view":"Gallery",()=>{gallery=!gallery;Results();}),0,5);
        Add(body,Pair(filters,actions),16);
        var filtered=Filtered().ToList();int pages=Math.Max(1,(filtered.Count+23)/24);page=Math.Min(page,pages-1);
        var layout=new UniformGrid{Columns=gallery?3:1};
        foreach(var asset in filtered.Skip(page*24).Take(24)){
            var f=asset;var check=new CheckBox{IsChecked=f.Selected,Content=T(f.name,13,Light,true),ToolTip=f.name};check.Checked+=(o,e)=>{f.Selected=true;Selection();};check.Unchecked+=(o,e)=>{f.Selected=false;Selection();};
            var titleBlock=new StackPanel();Add(titleBlock,check);
            var details=T(Format.Size(f.size)+"   ·   "+f.engine.ToUpperInvariant(),12,Muted);Add(titleBlock,details,5);
            var state=T(f.integrity=="verified_exact_match"?"✓  Matches original":"SHA-256 recorded",12,f.integrity=="verified_exact_match"?Mint:Muted);state.ToolTip=f.sha256;Add(titleBlock,state,4);
            FrameworkElement content;
            if(gallery){var stack=new StackPanel();stack.Children.Add(Preview(f));titleBlock.Margin=new Thickness(11,9,10,10);stack.Children.Add(titleBlock);content=stack;}
            else{content=Pair(titleBlock,T(f.Group,12,Muted));content.Margin=new Thickness(12,8,12,8);}
            var tile=Box(content,Panel,0,Line,8);tile.ClipToBounds=true;tile.Margin=new Thickness(0,0,8,8);layout.Children.Add(tile);
        }Add(body,layout,12);
        if(filtered.Count==0)Add(body,T("No candidates found with this method. Overwritten or trimmed data may be unavailable.",14,Muted),8);
        if(pages>1){var paging=Row();var prev=Btn("Previous",()=>{page--;Results();});prev.IsEnabled=page>0;var next=Btn("Next",()=>{page++;Results();});next.IsEnabled=page+1<pages;Add(paging,prev);Add(paging,T("Page "+(page+1)+" of "+pages,13,Muted),0,10);Add(paging,next,0,10);Add(body,paging,5);}
        var technical=new StackPanel();Add(technical,T("Image SHA-256   "+report.image_sha256+"\nCase   "+caseDir,12,Muted),7);
        if(report.metrics.ground_truth)Add(technical,T(report.metrics.unrecovered+" reference hashes missing",12,Muted),4);
        Add(technical,Btn("Open case and report",()=>OpenFolder(caseDir)),7);
        Add(body,new Expander{Header="Report and technical details",Content=technical},8);
        exportButton=Btn("Recover selected",async()=>await ExportFiles(),true);Selection();var bar=Row();Add(bar,exportButton);Add(bar,Btn("Return to workspace",Home),0,9);Add(body,bar,13);
    }
    IEnumerable<Asset> Filtered(){return report.files.Where(f=>filter=="All"||f.Group==filter);}
    async Task ExportFiles(){
        if(active!=null)return;
        var chosen=report.files.Where(f=>f.Selected).ToList();if(chosen.Count==0)return;
        active=new CancellationTokenSource();var token=active.Token;ProgressPage("Saving selected files");
        try{
            var receipt=await Task.Run(()=>Session.Export(caseDir,disk,chosen,token,Notify));
            Page("done","Workspace  /  Export");Heading(receipt.failed.Count==0?"Recovery complete":"Export finished with errors",receipt.verified.Count+" files saved",SourceTitle);
            var s=new StackPanel();Add(s,Icon("check",Mint,36));Add(s,T(receipt.failed.Count==0?"Export verified":"Export summary",23,Light,true),9);
            Add(s,T(receipt.verified.Count+" copies matched their scan hashes. "+receipt.failed.Count+" exports failed.",15,Muted),5);
            if(report.metrics.ground_truth)Add(s,T(chosen.Count(f=>f.integrity=="verified_exact_match")+" selected candidates matched known originals.",14,Mint),5);
            if(receipt.failed.Count>0)Add(s,T(String.Join("\n",receipt.failed),13,"#F0C5A6"),6);
            if(report.warnings.Count>0)Add(s,T(String.Join("\n",report.warnings),13,"#F0C5A6"),6);
            Add(s,T(receipt.destination,14,Muted),14);Add(body,Box(s,Panel,24),20);
            var actions=Row();Add(actions,Btn("Open recovered files",()=>OpenFolder(receipt.destination),true));Add(actions,Btn("Back to results",Results),0,8);Add(actions,Btn("Workspace",Home),0,8);Add(body,actions,16);
        }catch(Exception e){Problem("Export stopped",e.Message);}
        finally{timer.Stop();active.Dispose();active=null;}
    }
}
}
