import htcondor
from prometheus_client import start_http_server, Gauge
from collections import Counter, defaultdict
import time

# Define Prometheus metrics
WALLUSAGE = Gauge('total_wall_time_used_by_casa_hours', 'Total wall time used by CASA (in hours)')
PERUSERUSAGE = Gauge('wall_time_used_by_user_seconds', 'Wall time used per user (in seconds)', ["user"])
TOTAL_CPUS = Gauge('number_of_total_cpus_in_cluster', 'Number of CPUs in Cluster')
DEDICATED_CPUS = Gauge('number_dedicated_cpus_for_casa', 'Number of dedicated CPUs for CASA')
PERCENT_CPU_USED = Gauge('current_cpus_being_used_percentage', 'Percentage of dedicated CPUs currently in use')
ACCOUNTING_GROUP_USAGE = Gauge('slots_used_by_user', 'Slots currently in use by Accounting Group',["AccountingGroup"])
OCCUPANCY = Gauge('RemoteOwners', 'A gauge for who is using the cluster',['owner'])
NODE_CPU_EFF = Gauge('CPU_Eff','A gague for cpu utilization efficiency')
NODE_CPU_EFF_BY_CORE_COUNT = Gauge('NODE_EFF','A gauge for cpu efficiency by core count',['numcpus'])
def connect_to_negotiator(collector_name):
    """
    Connects to the HTCondor negotiator and returns the negotiator object.
    
    Args:
    collector_name (str): Name of the HTCondor collector to connect to.
    
    Returns:
    htcondor.Negotiator: The negotiator object.
    """
    # Initialize the collector and get the negotiator advertisement
    collector = htcondor.Collector(collector_name)
    neg_ad = collector.locate(htcondor.DaemonTypes.Negotiator, collector_name)
    neg = htcondor.Negotiator(neg_ad)
    return neg

def get_metrics(negotiator):
    """
    Fetches the priorities from the negotiator.
    
    Args:
    negotiator (htcondor.Negotiator): The negotiator object.
    
    Returns:
    list: A list of priorities.
    """
    priorities = negotiator.getPriorities(True)
    return priorities

def get_startd(collector_name):
    """
    Fetches the startd advertisements from the collector.
    
    Args:
    collector_name (str): Name of the HTCondor collector to connect to.
    
    Returns:
    list: A list of startd advertisements.
    """
    collector = htcondor.Collector(collector_name)
    startds = collector.query(htcondor.AdTypes.Startd)
    return startds

def get_occupancy(collector_name):
    """
    Fetches the occupancy from the collector.

    Args:
    collector_name (str): Name of the HTCondor collector to connect to.

    Returns:
    dictionary of remoteOwners.
    """
    collector = htcondor.Collector(collector_name)
    RemoteOwners_list = []
    slotState = collector.query(htcondor.AdTypes.Startd,"true",['Name','JobId','State','RemoteOwner','COLLECTOR_HOST_STRING','TotalCpus','LoadAvg'])
    for slot in slotState[:]:
        if (slot['State'] == "Claimed"):
            if "cms-jovyan" in slot['RemoteOwner']:
                RemoteOwners_list.append(str(slot['RemoteOwner']))
            else:
                for _ in range(int(slot['TotalCpus'])):
                    RemoteOwners_list.append(str(slot['RemoteOwner']))
    return(Counter(RemoteOwners_list))

def get_cluster_cpu_eff(collector_name):
    """
    Calculates the cluster CPU efficency
    Returns:
    fraction of load versus N CPU
    """
    cluster_eff =  0.0
    total_num_cpu = 0
    node_eff = 0.0
    collector = htcondor.Collector(collector_name)
    slotState = collector.query(htcondor.AdTypes.Startd,"true",['Name','JobId','State','RemoteOwner','COLLECTOR_HOST_STRING','TotalCpus','LoadAvg'])

    for slot in slotState[:]:
        if (slot['State'] == 'Claimed' and 'cms-jovyan' not in slot['RemoteOwner']):
            node_eff += slot['LoadAvg']
            total_num_cpu += slot['TotalCpus']
    cluster_eff = node_eff / total_num_cpu

    return(cluster_eff)

def get_node_cpu_eff(collector_name):
    """
    Calculates cpu eff and sorts by CPU count of node
    Returns:
    nothing, sets NODE_CPU_EFF_BY_CORE_COUNT metric
    """
    node_entry = defaultdict(list)
    total_num_cpu = 0
    node_eff = 0.0
    collector = htcondor.Collector(collector_name)
    slotState = collector.query(htcondor.AdTypes.Startd,"true",['Name','JobId','State','RemoteOwner','COLLECTOR_HOST_STRING','TotalCpus','LoadAvg'])

    for slot in slotState[:]:
        if (slot['State'] == 'Claimed' and 'cms-jovyan' not in slot['RemoteOwner']):
            node_eff = slot['LoadAvg'] / slot['TotalCpus']
            node_entry[str(slot['TotalCpus'])].append(node_eff)
    averages = {name: sum(pcts) / len(pcts) for name, pcts in node_entry.items()}
    for node in averages:
        NODE_CPU_EFF_BY_CORE_COUNT.labels(numcpus=node).set(averages[node])

if __name__ == '__main__':
    # Start the Prometheus HTTP server on port 9090
    start_http_server(9090)
    
    # Main loop for gathering and updating metrics
    while True:
        total_wall_usage = 0
        scanned_machines = []
        total_num_cpus_cluster = 0
        total_num_cpus_dedicated = 0
        Accounting_Groups = []
        in_use = 0
        
        # Connect to the negotiator and fetch metrics
        neg = connect_to_negotiator("red-condor.unl.edu")
        priorities = get_metrics(neg)
        
        # Update user-specific wall time usage
        for priority in priorities:
            user_name = priority.get("Name")
            if "jupyter" in user_name or "cms-jovyan@unl.edu" in user_name:
                total_wall_usage += priority.get("WeightedAccumulatedUsage")
                PERUSERUSAGE.labels(user=user_name).set(priority.get("WeightedAccumulatedUsage"))
        
        # Convert total wall usage from seconds to hours
        total_wall_usage_hours = total_wall_usage / 3600
        WALLUSAGE.set(total_wall_usage_hours)

        # Fetch startd data and calculate CPU usage
        startds = get_startd("red-condor.unl.edu")
        for startd in startds:
            cpus = int(startd.get("DetectedCpus"))
            machine_name = str(startd.get("Machine"))

            if machine_name not in scanned_machines:
                scanned_machines.append(machine_name)
                total_num_cpus_cluster += cpus
                if "cms-jovyan" in str(startd.get("Start")):
                    total_num_cpus_dedicated += cpus
                
                # Count CPUs currently in use by cms-jovyan users
                if "cms-jovyan" in str(startd.get("RemoteUser")):
                    in_use += 1
                    Accounting_Groups.append(str(startd.get("AccountingGroup")))
        Accounting_Groups_Usage = Counter(Accounting_Groups)
        for group in Accounting_Groups_Usage:
            ACCOUNTING_GROUP_USAGE.labels(AccountingGroup=group).set(Accounting_Groups_Usage[group])
        # Update the Prometheus metrics for CPU usage
        DEDICATED_CPUS.set(total_num_cpus_dedicated)
        TOTAL_CPUS.set(total_num_cpus_cluster)    
        PERCENT_CPU_USED.set(float(in_use) / float(total_num_cpus_dedicated) if total_num_cpus_dedicated > 0 else 0)
        slot_usage = get_occupancy('red-condor.unl.edu')
        NODE_CPU_EFF.set(get_cluster_cpu_eff('red-condor.unl.edu'))            
        for key, value in slot_usage.items():
            OCCUPANCY.labels(owner=key).set(value)
        get_node_cpu_eff('red-condor.unl.edu')
        # Sleep for 5 seconds before the next cycle
        time.sleep(5)

