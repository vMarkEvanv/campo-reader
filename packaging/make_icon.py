"""Render the existing C/book icon geometry into PNG-in-ICO using only stdlib."""
import math
import struct
import zlib
from pathlib import Path

def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
def pixel(x,y):
 # Matches public/campo-icon.svg: rounded blue square, C arc and three book lines.
 inside=abs(x-32)<=17 or abs(y-32)<=17 or (abs(x-32)-17)**2+(abs(y-32)-17)**2<=15**2
 if not inside:return (0,0,0,0)
 color=(40,107,145,255);cx=45-math.sqrt(19**2-12**2);dx=x-cx;dy=y-32
 if (abs(math.hypot(dx,dy)-19)<=3 and (dx<=0 or abs(math.atan2(dy,dx))>=math.atan2(12,45-cx))) or min(math.hypot(x-45,y-20),math.hypot(x-45,y-44))<=3:color=(255,255,255,255)
 for yy,end in ((24,40),(32,36),(40,40)):
  if math.hypot(x-min(end,max(26,x)),y-yy)<=1.5:color=(169,216,237,255)
 return color

def png(size):
 raw=bytearray();scale=64/size
 for y in range(size):
  raw.append(0)
  for x in range(size):
   colors=[pixel((x+dx)*scale,(y+dy)*scale) for dx,dy in ((.25,.25),(.75,.25),(.25,.75),(.75,.75))]
   raw.extend(round(sum(c[i] for c in colors)/4) for i in range(4))
 return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',size,size,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(raw,9))+chunk(b'IEND',b'')

def main():
 sizes=(16,32,48,64,256);images=[png(size) for size in sizes];offset=6+16*len(sizes);entries=[]
 for size,data in zip(sizes,images):
  entries.append(struct.pack('<BBBBHHII',size%256,size%256,0,0,1,32,len(data),offset));offset+=len(data)
 target=Path(__file__).resolve().parent/'campo.ico';target.write_bytes(struct.pack('<HHH',0,1,len(sizes))+b''.join(entries)+b''.join(images))
if __name__=='__main__':main()
