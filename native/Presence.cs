using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
namespace RecoverX {
// A present disk's parent chain also identifies USB Attached SCSI devices.
// This fallback only rules out absent USB disks. Source selection always needs Storage inventory.
public static class Presence{
    [StructLayout(LayoutKind.Sequential)] struct Device {public int Size;public Guid Class;public uint Instance;public IntPtr Reserved;}
    [DllImport("setupapi",CharSet=CharSet.Unicode,SetLastError=true)] static extern IntPtr SetupDiGetClassDevs(ref Guid id,string enumerator,IntPtr window,uint flags);
    [DllImport("setupapi",SetLastError=true)] static extern bool SetupDiEnumDeviceInfo(IntPtr set,uint index,ref Device data);
    [DllImport("setupapi")] static extern bool SetupDiDestroyDeviceInfoList(IntPtr set);
    [DllImport("cfgmgr32",CharSet=CharSet.Unicode)] static extern uint CM_Get_Device_ID(uint node,StringBuilder id,int len,int flags);
    [DllImport("cfgmgr32")] static extern uint CM_Get_Parent(out uint parent,uint node,int flags);
    public static bool? AnyUsb(){
        var cls=new Guid("4d36e967-e325-11ce-bfc1-08002be10318");
        IntPtr set=SetupDiGetClassDevs(ref cls,null,IntPtr.Zero,2);
        if(set==new IntPtr(-1))return null;
        try{
            bool uncertain=false;
            for(uint index=0;;index++){
                var dev=new Device{Size=Marshal.SizeOf(typeof(Device))};
                if(!SetupDiEnumDeviceInfo(set,index,ref dev))return Marshal.GetLastWin32Error()==259&&!uncertain?(bool?)false:null;
                uint node=dev.Instance;
                for(int depth=0;depth<48;depth++){
                    var id=new StringBuilder(1024);
                    if(CM_Get_Device_ID(node,id,id.Capacity,0)!=0){uncertain=true;break;}
                    var name=id.ToString();
                    if(name.StartsWith(@"USB\",StringComparison.OrdinalIgnoreCase)||name.StartsWith(@"USBSTOR\",StringComparison.OrdinalIgnoreCase))return true;
                    if(name.StartsWith(@"HTREE\ROOT\",StringComparison.OrdinalIgnoreCase))break;
                    uint next;if(CM_Get_Parent(out next,node,0)!=0||next==node){uncertain=true;break;}node=next;
                }
            }
        }finally{SetupDiDestroyDeviceInfoList(set);}
    }
}
}
