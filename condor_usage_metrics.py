import htcondor
from prometheus_client import start_http_server, Gauge
from collections import Counter
import time

# Define Prometheus metrics
WALLUSAGE = Gauge('total_wall_time_used_by_casa_hours', 'Total wall time used by CASA (in hours)')
PERUSERUSAGE = Gauge('wall_time_used_by_user_seconds', 'Wall time used per user (in seconds)', ["user"])
DEDICATED_CPUS = Gauge('number_dedicated_cpus_for_casa', 'Number of dedicated CPUs for CASA')
PERCENT_CPU_USED = Gauge('current_cpus_being_used_percentage', 'Percentage of dedicated CPUs currently in use')
ACCOUNTING_GROUP_USAGE = Gauge('slots_used_by_user', 'Slots currently in use by Accounting Group',["AccountingGroup"])
OCCUPANCY = Gauge('RemoteOwners', 'A gauge for who is using the cluster',['owner'])

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
    slotState = collector.query(htcondor.AdTypes.Startd,"true",['Name','JobId','State','RemoteOwner','COLLECTOR_HOST_STRING'])
    for slot in slotState[:]:
        if (slot['State'] == "Claimed"):
            RemoteOwners_list.append(str(slot['RemoteOwner']))
    return(Counter(RemoteOwners_list))


if __name__ == '__main__':
    # Start the Prometheus HTTP server on port 9090
    start_http_server(9090)
    
    # Main loop for gathering and updating metrics
    while True:
        total_wall_usage = 0
        scanned_machines = []
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
            if "cms-jovyan" in str(startd.get("Start")):
                cpus = int(startd.get("DetectedCpus"))
                machine_name = str(startd.get("Machine"))
                # Track CPUs dedicated to CASA
                if machine_name not in scanned_machines:
                    scanned_machines.append(machine_name)
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
        PERCENT_CPU_USED.set(float(in_use) / float(total_num_cpus_dedicated) if total_num_cpus_dedicated > 0 else 0)
        # Sleep for 5 seconds before the next cycle
        slot_usage = get_occupancy('red-condor.unl.edu')
            
        for key, value in slot_usage.items():
            OCCUPANCY.labels(owner=key).set(value)

        time.sleep(5)

