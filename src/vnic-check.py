#!/QOpensys/pkgs/bin/python3

# Checks all of the vNIC configurations for all systems on the specified HMC and prints or emails the
#  results if there are any problems.
# You MUST change this file to contain your information or it will not do anything!
# Find the current version on Github at https://github.com/IBM/blog-vios4i
# See https://blog.vios4i.com for setup and usage instructions
# Eclipse Public License v2.0
# license: epl-2.0 

import io
import smtplib
import subprocess
from time import sleep

# Parameters that you can change to meet your requirements


# If SMTP host is None - the output will be printed to stdout, not emailed
smtphost = None # replace None with your smtphost name or IP address. 127.0.0.1 for a local mailserver
sender = 'senderaddress@yourdomain.tld'  # Sender address for email - probably needs to be a valid address in your domain
toaddrs = ['youraddress@yourdomain.tld'] # List of addresses that should get an email - seperate with commas

hmcs = ['monitor@hmcaddress'] # List of hmc user@address, seperate multiple entries with commas

minopercount=2 # Required minimum number of operational backing devices per vNIC

# Code from here on:

def run_hmc_query(hmc, basecmd, namelist):
  """Runs a query command on HMC and parses output
  
  Runs a query command on the specified HMC and parses the output into an array of hashes
   that map field names to field values - one array element per line - like a database
   query function.

 Parameters are passed by position AND keyword hash reference
   1 (required)  :  The hmc host name where the command should be run
   2 (required)  :  The base comand to be run.  Usually 'lssyscfg' with some options.
   3 (required)  :  a reference to an Array of field names to retreive.

 Returns a list of disctionaries of field names to field contents.  One element per line returned
  by the HMC command.

 Example call:
      alllpars = run_on_hmc(hmc,
                            "lssyscfg -r lpar -m sysname ",
                             ['name',lpar_id','lpar_env','curr_profile','state']
                             );
"""

  command = basecmd + ' --header -F ' + '%'.join(namelist);
  readdata=''

  process = subprocess.run(["ssh",hmc,"-o","BatchMode=yes",command],stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding="utf-8", universal_newlines=True) 
  if (process.returncode != 0):
    print("Error processing SSH Command: "+command)
    print(process.stderr)
    return([])
  readdata = process.stdout
  if ("No results were found." in readdata):
    return([])
  
  cmdResp = readdata.split("\n")
  
  hdr = cmdResp.pop(0).split('%')
  
  rtndata = []
  
  for line in cmdResp:
    mydict = dict()
    d=line.split("%")
    if (len(d) == len(hdr)) :
      for i in range(len(d)):
        mydict[hdr[i]]=d[i]
      rtndata.append(mydict)
    
  return rtndata


def structuredfield(data,namelist):
  """extract a list of HMC structured fields
  
  This function extracts a list of dictionaries from an HMC structured field that contains a comma seperated list of slash delimited values.  WARNING: this
  will not handle the crazy quoting on fileds like virtual_fc_adapters.
  
  Parameter 1 - the data to be parsed
  Paramater 2 - An ordered list of the field names for the slash delimited values for each list item
  
  Example Call: backingstate = structuredfield(vnic['backing_device_states'],['sriov','sriov-logical-port-ID','active','status'])
  
  Example of  the format processed:
    sriov/2701c001/1/Operational,sriov/27018001/0/Operational,sriov/27018002/0/NotOperational
    
  Example of output from that data:
    [{'sriov': 'sriov', 'sriov-logical-port-ID': '2701c001', 'active': '1', 'status': 'Operational'}, {'sriov': 'sriov', 'sriov-logical-port-ID': '27018001', 'active': '0', 'status': 'Operational'}, {'sriov': 'sriov', 'sriov-logical-port-ID': '27018002', 'active': '0', 'status': 'NotOperational'}]
    
  """
  
  rtndata=[]
  
  for group in data.split(','):
    mydict = dict()
    d = group.split('/')
    for i in range(max(len(d),len(namelist))):
      mydict[namelist[i]]=d[i]
    rtndata.append(mydict)
    
  return rtndata
  
  
def byprty(bdev):
  """sort function to allow sorting of backing device dictionaries by failover-priority"""
  
  return bdev['failover-priority']

#
## Start of Mainline
#

email = io.StringIO() # String stream to collect output
sendemail = False
  
# Create an email header
toaddrout = ",".join(toaddrs);
print(f"""From: <{sender}>
To: {toaddrout}
Subject: vNIC Status

""", file=email);


for hmcname in hmcs:

  syslist = run_hmc_query(hmcname,'lssyscfg -r sys',['name','type_model','serial_num','state'])
  
  for sys in syslist:
    if (sys['state'] != "Operating"):
      iter
      
    sysname = sys['name']
    
    syshdr = f"System: {sys['name']}  Model: {sys['type_model']}  S/N: {sys['serial_num']}"
  
    # these will be parameters
    vniclist = run_hmc_query(hmcname,f'lshwres -m {sysname} -r virtualio --rsubtype vnic',['lpar_name','lpar_id','slot_num','auto_priority_failover','backing_devices','backing_device_states'])
    
    
    # get all SRIOV physical port data for system
    allports = run_hmc_query(hmcname,f'lshwres -m {sysname} -r sriov --rsubtype physport --level eth',['adapter_id','phys_port_id','phys_port_label','phys_port_sub_label','phys_port_loc'])
    allports.extend(run_hmc_query(hmcname,f'lshwres -m {sysname} -r sriov --rsubtype physport --level ethc',['adapter_id','phys_port_id','phys_port_label','phys_port_sub_label','phys_port_loc']))
    allports.extend(run_hmc_query(hmcname,f'lshwres -m {sysname} -r sriov --rsubtype physport --level roce',['adapter_id','phys_port_id','phys_port_label','phys_port_sub_label','phys_port_loc']))
    
    # create a lookup dictionary from adapterid-phys_port_id to the physical port details from lshwres sriov physport
    portlookup = dict()
    for p in allports:
      portlookup[p['adapter_id']+"-"+p['phys_port_id']]=p
    
    for vnic in vniclist:
      backinglist = structuredfield(vnic['backing_devices'],['sriov','vios-lpar-name','vios-lpar-ID','sriov-adapter-ID','sriov-physical-port-ID','sriov-logical-port-ID',
      'current-capacity','desired-capacity','failover-priority','current-max-capacity','desired-max-capacity'])
      backingstate = structuredfield(vnic['backing_device_states'],['sriov','sriov-logical-port-ID','active','status'])
    
      # make a lookup table by sriov-logical-port-id
      statlookup = dict()
      for bstate in backingstate:
        statlookup[bstate['sriov-logical-port-ID']]=bstate
    
      lastprty = '00'
      prtyerror = False
      dupprty = set() # Failover priorities that are duplicated
      viosdup = [] # VIOS with multiple backing devices for vNIC
      notoper = [] # list of non-operational backing devices
      opercount = 0 # how many operational backing devices
      viosset = set() # used to track which VIOS have been seen already
      for bdev in sorted(backinglist,key=byprty):
        bstate = statlookup[bdev['sriov-logical-port-ID']]
        bdev['state']=bstate
        if (lastprty == '00' and bstate['active'] != '1'):
         prtyerror = True
        if (lastprty == bdev['failover-priority']):
          dupprty.add(bdev['failover-priority'])
        lastprty=bdev['failover-priority']
        if bdev['vios-lpar-name'] in viosset:
          viosdup.append(bdev['vios-lpar-name'])
        viosset.add(bdev['vios-lpar-name'])
        if bstate['status'] == 'Operational':
          opercount += 1
        else:
          notoper.append(bdev['sriov-adapter-ID']+"-"+bdev['sriov-physical-port-ID'])
    
      # Generate email contents for errors in this vNIC      
      if (prtyerror or len(dupprty) > 0 or viosdup > 0 or notoper > 0 or opercount < minopercount):
        sendemail = True
        if (syshdr is not None):
          print(syshdr,file=email)
          syshdr = None
        print("Problems with vNIC on LPAR "+vnic['lpar_name']+"(id "+vnic['lpar_id']+") Slot "+vnic['slot_num'], file=email)
        if (prtyerror):
          print("   - Lowest priority interface is not the active interface", file=email)
        for dup in dupprty:
          print("   - failover priority "+dup+" is duplicated", file=email)
        for v in viosdup:
          print("   - Multiple backing devices on VIOS "+v, file=email)
        for dev in notoper:
          print("   - SRIOV physical port "+portlookup[dev]['phys_port_loc']+" is not operational",file=email)
        if (opercount < minopercount): 
          print("   - Less than "+str(minopercount)+" operational backing devices ("+str(opercount)+")", file=email)
        print(file=email)
  
  
# Print the result or send an email

if smtphost is None:
  print(email.getvalue())
  
elif sendemail:
  smtpobj = None
  for trynum in range(5):
    try:
      smtpobj = smtplib.SMTP(smtphost,25)
      smtpobj.sendmail(sender, toaddrs, email.getvalue())         
      break
    except:
      print(f"Error: unable to send email on try {trynum}, waiting 30 seconds to retry")
      sleep(30)
    finally:
      if smtpobj:
        smtpobj.quit()

email.close()  


