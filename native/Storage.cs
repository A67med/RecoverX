using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Linq;
using System.Management;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace RecoverX {
public sealed class UsbDisk {
    public int Number {get;set;} public long Size {get;set;} public int Sector {get;set;}
    public string Name {get;set;} public string Interface {get;set;} public string Identity {get;set;}
    public string Volumes {get;set;} public string Serial {get;set;}
}
public static class Storage {
    const string Scope=@"\\.\root\Microsoft\Windows\Storage";
    [DllImport("kernel32",CharSet=CharSet.Unicode,SetLastError=true)]
    static extern SafeFileHandle CreateFile(string path,uint access,uint share,IntPtr security,uint mode,uint flags,IntPtr template);
    [DllImport("kernel32",SetLastError=true)]
    static extern bool DeviceIoControl(SafeFileHandle h,uint code,byte[] input,int inputLength,byte[] output,int size,out int returned,IntPtr overlapped);
    [DllImport("kernel32",CharSet=CharSet.Unicode,SetLastError=true)]
    static extern bool GetVolumePathName(string path,StringBuilder volume,int length);
    [DllImport("kernel32",CharSet=CharSet.Unicode,SetLastError=true)]
    static extern bool GetVolumeNameForVolumeMountPoint(string mount,StringBuilder volume,int length);
    [DllImport("kernel32",SetLastError=true)] static extern IntPtr VirtualAlloc(IntPtr address,UIntPtr size,uint allocation,uint protect);
    [DllImport("kernel32")] static extern bool VirtualFree(IntPtr address,UIntPtr size,uint operation);
    [DllImport("kernel32",SetLastError=true)] static extern bool ReadFile(SafeFileHandle h,IntPtr buffer,int size,out int read,IntPtr overlapped);
    static IOException WinError(string context) { return new IOException(context+" "+new Win32Exception(Marshal.GetLastWin32Error()).Message); }
    static SafeFileHandle Open(string path,uint access) {
        var h=CreateFile(path,access,3,IntPtr.Zero,3,0,IntPtr.Zero);
        if(h.IsInvalid){h.Dispose();throw WinError("Windows could not open the storage device.");}
        return h;
    }
    static byte[] Query(SafeFileHandle h,uint code,byte[] input,int size,int minimum) {
        byte[] buffer=new byte[size]; int n;
        if(!DeviceIoControl(h,code,input,input==null?0:input.Length,buffer,size,out n,IntPtr.Zero))throw WinError("Windows could not verify disk information.");
        if(n<minimum)throw new IOException("Incomplete disk information from Windows.");
        return buffer.Take(n).ToArray();
    }
    public static bool Eligible(int bus,bool? boot,bool? system,bool? offline,long size,int sector) {
        return bus==7 && boot==false && system==false && offline==false && size>0 &&
               (sector==512||sector==1024||sector==2048||sector==4096) && size%sector==0;
    }
    static string Text(ManagementBaseObject row,string field){return Convert.ToString(row[field]).Trim();}
    public static List<UsbDisk> Discover() {
        var result=new List<UsbDisk>();
        using(var search=new ManagementObjectSearcher(Scope,"SELECT * FROM MSFT_Disk WHERE BusType=7"))
        using(var rows=search.Get()) foreach(ManagementObject r in rows) using(r) {
            int sector=Convert.ToInt32(r["LogicalSectorSize"]); long size=Convert.ToInt64(r["Size"]);
            if(!Eligible(Convert.ToInt32(r["BusType"]),r["IsBoot"] as bool?,r["IsSystem"] as bool?,r["IsOffline"] as bool?,size,sector))continue;
            var disk=new UsbDisk {Number=Convert.ToInt32(r["Number"]),Size=size,Sector=sector,Name=Text(r,"FriendlyName"),
                Serial=Text(r,"SerialNumber"),Interface=Text(r,"Path")};
            if(!disk.Interface.StartsWith(@"\\?\",StringComparison.Ordinal)||disk.Interface.Length<12)continue;
            string stable=disk.Interface+"|"+Text(r,"UniqueId")+"|"+disk.Serial+"|"+disk.Number+"|"+size+"|"+sector;
            using(var sha=SHA256.Create())disk.Identity=BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(stable))).Replace("-","");
            var mounts=new List<string>();
            using(var parts=new ManagementObjectSearcher(Scope,"SELECT DriveLetter FROM MSFT_Partition WHERE DiskNumber="+disk.Number))
            using(var partitions=parts.Get())foreach(ManagementObject p in partitions)using(p){
                var letter=Convert.ToChar(p["DriveLetter"]??'\0');
                if(letter<'A'||letter>'Z')continue;
                var desc=letter+":";
                try{var drive=new DriveInfo(desc);desc+="  "+drive.DriveFormat;if(!String.IsNullOrWhiteSpace(drive.VolumeLabel))desc+="  "+drive.VolumeLabel;}catch(IOException){}
                mounts.Add(desc);
            }
            disk.Volumes=mounts.Count==0?"No mounted volume":String.Join("  ·  ",mounts);
            result.Add(disk);
        }
        return result;
    }
    public static string LocalFolder(string folder) {
        if(String.IsNullOrWhiteSpace(folder))throw new IOException("Choose an existing local folder.");
        folder=Path.GetFullPath(folder);
        if(folder.Length<3 || folder[1]!=':' || !Directory.Exists(folder))throw new IOException("Choose an existing folder on a local disk.");
        for(var dir=new DirectoryInfo(folder);dir!=null;dir=dir.Parent)
            if((dir.Attributes & FileAttributes.ReparsePoint)!=0)throw new IOException("Choose a folder outside junctions, mounted folders and cloud placeholders.");
        if(new DriveInfo(Path.GetPathRoot(folder)).DriveType!=DriveType.Fixed)
            throw new IOException("Choose a destination on a fixed local disk.");
        return folder;
    }
    static int PhysicalVolume(string path) {
        var mount=new StringBuilder(1024);var name=new StringBuilder(1024);
        if(!GetVolumePathName(path,mount,1024)||!GetVolumeNameForVolumeMountPoint(mount.ToString(),name,1024))
            throw WinError("Cannot identify the destination volume.");
        using(var handle=Open(name.ToString().TrimEnd('\\'),0)){
            var b=Query(handle,0x560000,null,4096,32);
            if(BitConverter.ToUInt32(b,0)!=1)throw new IOException("Spanned volumes cannot be verified as a single disk.");
            return BitConverter.ToInt32(b,8);
        }
    }
    public static void ValidateDisks(int source,int output,int system,int outputBus) {
        if(source==output || source==system)throw new IOException("The source must be separate from the Windows disk and the destination disk.");
        // Limit output to directly attached, non-virtual fixed storage.
        if(!new[]{3,10,11,17}.Contains(outputBus))throw new IOException("Choose an internal ATA, SATA, SAS or NVMe disk. The current backing storage cannot be verified.");
    }
    public static void ValidateImageDestination(string folder){
        LocalFolder(folder);
        if(!String.Equals(Path.GetPathRoot(folder),Path.GetPathRoot(Environment.SystemDirectory),StringComparison.OrdinalIgnoreCase))
            ValidateOutput(new UsbDisk{Number=-1},folder);
    }
    public static void ValidateOutput(UsbDisk source,string folder) {
        int output=PhysicalVolume(LocalFolder(folder));
        int system=PhysicalVolume(Environment.SystemDirectory);
        using(var handle=Open(@"\\.\PhysicalDrive"+output,0)){
            int bus=BitConverter.ToInt32(Query(handle,0x2d1400,new byte[12],8192,32),28);
            ValidateDisks(source.Number,output,system,bus);
        }
    }
    public static SafeFileHandle OpenSelected(UsbDisk selected,string destination) {
        ValidateOutput(selected,destination);
        var handle=Open(selected.Interface,0x80000000); // GENERIC_READ, OPEN_EXISTING
        try {
            var number=Query(handle,0x2d1080,null,12,12);
            var length=Query(handle,0x7405c,null,8,8);
            var descriptor=Query(handle,0x2d1400,new byte[12],8192,32);
            if(BitConverter.ToInt32(number,4)!=selected.Number || BitConverter.ToInt64(length,0)!=selected.Size ||
               BitConverter.ToInt32(descriptor,28)!=7 || !Discover().Any(d=>d.Identity==selected.Identity))
                throw new IOException("The selected USB changed. Refresh and select it again.");
            return handle;
        }catch{handle.Dispose();throw;}
    }
    public static void StreamDisk(SafeFileHandle handle,UsbDisk disk,Stream output){
        const int chunk=1024*1024;
        IntPtr aligned=VirtualAlloc(IntPtr.Zero,(UIntPtr)chunk,0x3000,4);
        if(aligned==IntPtr.Zero)throw WinError("Cannot allocate an aligned read buffer.");
        var bytes=new byte[chunk];
        try{
            for(long offset=0;offset<disk.Size;){
                int wanted=(int)Math.Min(chunk,disk.Size-offset), got;
                if(!ReadFile(handle,aligned,wanted,out got,IntPtr.Zero))throw WinError("The USB stopped responding.");
                if(got!=wanted)throw new EndOfStreamException("Short USB read. Check the connection.");
                Marshal.Copy(aligned,bytes,0,got);output.Write(bytes,0,got);offset+=got;
            }
        }finally{VirtualFree(aligned,UIntPtr.Zero,0x8000);}
    }
}
}
