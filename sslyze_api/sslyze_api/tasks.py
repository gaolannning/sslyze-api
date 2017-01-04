from sslyze.plugins_finder import PluginsFinder
from sslyze.plugins_process_pool import PluginsProcessPool
from sslyze.server_connectivity import ServerConnectivityInfo, ServerConnectivityError
from sslyze.ssl_settings import TlsWrappedProtocolEnum
from sslyze_api import celery_app
#import sslyze.plugins.plugin_base

import ujson as json
from subprocess import Popen, PIPE


def parse_certinfo(certinfo):
    """ Parses the certinfo generated by the sslyze and returns a dict    """

    tmp_certinfo = {}
    for key,val in certinfo.iteritems():

        if key in ['path_validation_result_list','server_info','plugin_command','plugin_options']:
            """ ignore this info """
            pass

        elif key in ['certificate_chain','verified_certificate_chain']:
            if key == 'verified_certificate_chain':
                count = 0
                tmp_chain = {}
                for cert in val:
                    # only store pem for now
                    #tmp_chain[count] = {'pem': cert.as_pem, 'sha1_fingerprint':cert.sha1_fingerprint, 'dict': cert.as_dict}
                    tmp_chain[count] = {'pem': cert.as_pem,
                            'sha1_fingerprint':cert.sha1_fingerprint, 'hpkp_pin':cert.hpkp_pin}
                    count += 1
                tmp_certinfo[key] = tmp_chain
        else:
            tmp_certinfo[key] = val

    return tmp_certinfo

@celery_app.task
def scan(hostname, port):
    # Setup the servers to scan and ensure they are reachable
    try:
        server_info = ServerConnectivityInfo(hostname=hostname, port=port)
        server_info.test_connectivity_to_server()
    except ServerConnectivityError as e:
        # Could not establish an SSL connection to the server
        raise RuntimeError('Error when connecting to {}: {}'.format(hostname, e.error_msg))

    # Get the list of available plugins
    sslyze_plugins = PluginsFinder()

    # Create a process pool to run scanning commands concurrently
    plugins_process_pool = PluginsProcessPool(sslyze_plugins)

    # Queue some scan commands; the commands are same as what is described in the SSLyze CLI --help text.
    # print '\nQueuing some commands...'
    plugins_process_pool.queue_plugin_task(server_info, 'sslv3')
    plugins_process_pool.queue_plugin_task(server_info, 'certinfo_basic')
    plugins_process_pool.queue_plugin_task(server_info, 'tlsv1')
    plugins_process_pool.queue_plugin_task(server_info, 'tlsv1_1')
    plugins_process_pool.queue_plugin_task(server_info, 'tlsv1_2')
    plugins_process_pool.queue_plugin_task(server_info, 'sslv2')

    result = {}

    result['server_info'] = server_info.__dict__
    for res in plugins_process_pool.get_results():
        if res.plugin_command in ['sslv2','sslv3','tlsv1','tlsv1_1','tlsv1_2']:
            supported = False
            if len(res.accepted_cipher_list) > 0:
                supported = True
            acc_ciphers = []
            rej_ciphers = []
            for cipher in res.accepted_cipher_list:
                acc_ciphers.append(cipher.name)

            result[res.plugin_command] = {'supported': supported, 'accepted_ciphers': acc_ciphers}
        elif res.plugin_command == 'certinfo_basic':
            result['certinfo'] = parse_certinfo(res.__dict__)

    return result


# returns result in json
@celery_app.task
def scan_cli(hostname, port):
    cmd = ['python','-m','sslyze','--regular',hostname+':'+str(port), '--json_out=-']
    proc = Popen(cmd, stdout=PIPE, stderr=PIPE)
    out, err = proc.communicate()
    return json.loads(out)
