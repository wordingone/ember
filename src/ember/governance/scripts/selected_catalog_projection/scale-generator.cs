using System;
using System.IO;
using System.Text.Json;
using System.Text;
using System.Diagnostics;
public static class MemoryScaleGenerator {
    const int Members=130578,Hashes=130103,AllIds=293852,ReceiptCount=4096;
    static readonly JsonSerializerOptions Options=new JsonSerializerOptions{DefaultBufferSize=65536};
    static string Sha(long n){return n.ToString("x64");}
    static string Id(string prefix,int n){string value=prefix+n.ToString("D8")+new string('x',15);if(n==0)value=value.Substring(0,value.Length-1)+"\"";if(n==1)value=value.Substring(0,value.Length-1)+"\\";if(n==2)value=value.Substring(0,value.Length-1)+"\n";if(n==3)value=value.Substring(0,value.Length-1)+"é";return value;}
    static string Dataset(int n){return "dataset:issue1581-bulk-train:scale-"+n;}
    static void Row(Stream stream,object row,ref bool first){if(!first)stream.WriteByte(44);first=false;JsonSerializer.Serialize(stream,row,Options);}
    public static object Generate(string path) {
        var watch=Stopwatch.StartNew();var proc=Process.GetCurrentProcess();long peak=0;
        // Conservative construction estimate, before writing. Actual occupancy is checked below and again after serialization.
        long estimate=checked(AllIds*320L+Hashes*170L+Members*155L+Hashes*210L+ReceiptCount*100L+Members*420L+Hashes*270L+4L*1024*1024);
        if(estimate>256L*1024*1024)throw new InvalidOperationException("SCALE_ESTIMATE_ABOVE_256_MIB");
        using(var stream=new FileStream(path,FileMode.CreateNew,FileAccess.Write,FileShare.None,65536,FileOptions.SequentialScan)) {
            byte[] start=Encoding.UTF8.GetBytes("{\"records\":[");stream.Write(start,0,start.Length);bool first=true;
            for(int i=0;i<8;i++)Row(stream,new{kind="dataset_version",id=Dataset(i),state="admitted"},ref first);
            for(int i=0;i<AllIds;i++) {
                bool selected=i<Members;int other=i-Members;
                string split=selected||other==163273?"train":"validation";
                string admission=selected||other<162665||other==163273?"admitted":"pending";
                long hash=selected?1+i%Hashes:2000000L+other;
                Row(stream,new{kind="membership",id=Id("m",i),exact_sha256=Sha(hash),split=split,admission_state=admission,tokenizer_sha256=new string('a',64),window_start=0,window_end=10},ref first);
                if(i%4096==0){proc.Refresh();peak=Math.Max(peak,proc.PrivateMemorySize64);if(peak>536870912L||watch.Elapsed.TotalSeconds>900||stream.Position>200L*1024*1024)throw new InvalidOperationException("SCALE_GENERATOR_CAP");}
            }
            for(int i=0;i<Hashes;i++)Row(stream,new{kind="immutable_object",id=Id("o",i),sha256=Sha(1+i)},ref first);
            for(int i=0;i<ReceiptCount;i++)Row(stream,new{kind="receipt",sha256=Sha(1000000000L+i)},ref first);
            byte[] middle=Encoding.UTF8.GetBytes("],\"edges\":[");stream.Write(middle,0,middle.Length);first=true;
            for(int i=0;i<Members;i++)Row(stream,new{kind="version_membership",from_id=Dataset(i%8),to_id=Id("m",i)},ref first);
            for(int i=0;i<Hashes;i++)Row(stream,new{kind="object_receipt",from_id="object:"+Sha(1+i),to_id="receipt:"+Sha(1000000000L+i%ReceiptCount)},ref first);
            stream.WriteByte(93);stream.WriteByte(125);stream.Flush(true);
            if(stream.Position>200L*1024*1024)throw new InvalidOperationException("SCALE_GENERATOR_INPUT_CAP");
            return new{selected_members=Members,selected_hashes=Hashes,total_membership_ids=AllIds,receipt_rows=ReceiptCount,object_receipt_edges=Hashes,receipt_fanout_per_object=1,export_bytes=stream.Position,estimated_total_input_and_output_upper_bytes=estimate,generator_private_bytes_peak_sampled=peak,generator_elapsed_seconds=watch.Elapsed.TotalSeconds,field_coverage="IDs: 24 Unicode characters, 24-25 UTF8 bytes; quotes, backslash, LF and e-acute at four positions. Dataset IDs 34 characters, sha/tokenizer 64 ASCII, windows 0/10. Receipt rows 4096 distinct, one link per selected digest.",uncovered="Longer IDs up to 4096 captured UTF8 bytes, extensive escaping/Unicode, larger receipt row cardinalities, duplicate receipt hash rows, many receipts per object, other field length and receipt distributions; production fit remains unproved."};
        }
    }
}
