function Add-MyNewVpn() 
{
    # ����
    $VpnName="Goldenstand_L2TP"
    # ���ӵ�ַ
    $VpnAddr="113.125.202.170"
    # Ԥ������Կ
    $L2tpPsk="Password01"
    # DNS ������
    $Dns="172.16.6.100"
    # DNS ��׺ƥ��˺�׺����ָ���� DNS ����������
    $DnsSuffix="dev.goldenstand.cn"
    # ����ʱ��������Щ��ַʱ�����ӵ�·�ɱ�vpn
    $InternalIpAddress=@('10.10.10.0/24','172.16.6.0/24','172.16.7.0/24','192.168.1.0/24')
    
    $VpnOpts=@{
        Name = $VpnName
        TunnelType = "L2TP"
        ServerAddress = $VpnAddr
        EncryptionLevel = "Required"
        L2TP = $L2tpPsk
        SplitTunneling = $true
        RememberCredential = $true
        Force = $true
    }

    if ($VpnConn = Get-VpnConnection -Name $VpnName -ErrorAction SilentlyContinue)
    {  
        if ('Disconnected' -ne $VpnConn.ConnectionStatus) {
            Write-Error "VPN ���� '$VpnName' ����ʹ�ã���Ͽ�������"
            return;
        }

        $Selection = Read-Host "VPN ���� '$VpnName' �Ѵ���, ����ɾ���ɵ�����? (Y/N)"

        If ($Selection -eq "N")
        {
            Write-Output "ȡ������"
            return
        }

        Remove-VpnConnection -Name $VpnName -Force -ErrorAction Stop
    }

    Add-VpnConnection @VpnOpts -ErrorAction Stop
    Add-VpnConnectionTriggerTrustedNetwork -ConnectionName $VpnName -DnsSuffix $DnsSuffix -Force
    Add-VpnConnectionTriggerDnsConfiguration -ConnectionName $VpnName -DnsSuffix $DnsSuffix -DnsIPAddress $Dns -Force

    foreach ($ipAddr in $InternalIpAddress) 
    {
        Add-VpnConnectionRoute -ConnectionName $VpnName -DestinationPrefix $ipAddr -ErrorAction Stop
    }

    REG ADD HKLM\SYSTEM\CurrentControlSet\Services\PolicyAgent /v AssumeUDPEncapsulationContextOnSendRule /t REG_DWORD /d 0x2 /f
    REG ADD HKLM\SYSTEM\CurrentControlSet\Services\RasMan\Parameters /v ProhibitIpSec /t REG_DWORD /d 0x0 /f

    Write-Output "VPN ���� '$VpnName' ������"
}

function Test-Administrator  
{  
    $user = [Security.Principal.WindowsIdentity]::GetCurrent();
    (New-Object Security.Principal.WindowsPrincipal $user).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)  
}

if (-Not (Test-Administrator))
{
    Write-Output "�˽ű������Թ���ԱȨ��ִ�У������Թ���ԱȨ�޴��´���";
    pause
    Start-Process PowerShell -Verb RunAs "-NoProfile -ExecutionPolicy Bypass -Command `"cd '$pwd'; & '$PSCommandPath';`"";
    exit 1;
}
else 
{
    Add-MyNewVpn
    pause
}