// PyPNM Web GUI - Main Application
// SPDX-License-Identifier: Apache-2.0

const { createApp } = Vue;

const API_BASE = '/api';

createApp({
    data() {
        return {
            // Navigation
            currentView: 'home',
            
            // API Status
            apiStatus: 'mock',
            
            // Loading state
            isLoading: false,
            loadingSystemInfo: false,
            runningTest: false,
            
            // Search parameters
            searchType: 'ip',
            searchValue: '',
            snmpCommunity: 'Z1gg0@LL',
            snmpCommunityRW: 'Z1gg0Sp3c1@l',
            snmpCommunityModem: 'm0d3m1nf0',
            selectedCmts: '',
            selectedInterface: '',
            searchPerformed: false,
            cmtsSearch: '',
            
            // Data
            modems: [],
            cmtsList: [],
            cmtsListFull: [],  // Full CMTS list for filtering
            cmtsInterfaces: [],
            selectedModem: null,
            systemInfo: null,
            dsChannels: [],
            usChannels: [],
            rxmerData: null,
            spectrumData: null,
            eventLog: [],
            
            // Live modem loading
            loadingLiveModems: false,
            liveModemSource: '',
            enrichModems: false,
            
            // Charts
            charts: {}
        };
    },
    
    computed: {
        searchPlaceholder() {
            const placeholders = {
                'ip': 'e.g., 192.168.100.10',
                'mac': 'e.g., aa:bb:cc:dd:ee:01',
                'name': 'e.g., CM-Residential'
            };
            return placeholders[this.searchType] || 'Enter search value';
        }
    },
    
    async mounted() {
        // Check API health
        await this.checkApiHealth();
        
        // Load CMTS list
        await this.loadCmtsList();
        
        // Don't load mock modems - only show live data from CMTS
        // await this.searchModems();
    },
    
    methods: {
        // ============== API Calls ==============
        
        async checkApiHealth() {
            try {
                const response = await fetch(`${API_BASE}/health`);
                const data = await response.json();
                this.apiStatus = data.status;
            } catch (error) {
                console.error('API health check failed:', error);
                this.apiStatus = 'mock';
            }
        },
        
        async loadCmtsList() {
            try {
                const response = await fetch(`${API_BASE}/cmts`);
                const data = await response.json();
                if (data.status === 'success') {
                    // Transform the appdb format to our format
                    const cmtsList = data.cmts_list.map(cmts => ({
                        name: cmts.HostName,
                        ip: cmts.IPAddress,
                        vendor: cmts.Vendor,
                        type: cmts.Type,
                        alias: cmts.Alias || ''
                    }));
                    this.cmtsListFull = cmtsList;
                    this.cmtsList = cmtsList;
                    console.log(`Loaded ${this.cmtsList.length} CMTS systems from appdb`);
                }
            } catch (error) {
                console.error('Failed to load CMTS list:', error);
            }
        },
        
        filterCmtsList() {
            if (!this.cmtsSearch) {
                this.cmtsList = this.cmtsListFull;
            } else {
                const search = this.cmtsSearch.toLowerCase();
                this.cmtsList = this.cmtsListFull.filter(cmts => 
                    cmts.name.toLowerCase().includes(search) ||
                    cmts.alias.toLowerCase().includes(search) ||
                    cmts.ip.toLowerCase().includes(search) ||
                    cmts.vendor.toLowerCase().includes(search)
                );
            }
        },
        
        async loadCmtsInterfaces() {
            this.cmtsInterfaces = [];
            this.selectedInterface = '';
            
            if (!this.selectedCmts) return;
            
            try {
                const response = await fetch(`${API_BASE}/cmts/${this.selectedCmts}/interfaces`);
                const data = await response.json();
                if (data.status === 'success') {
                    this.cmtsInterfaces = data.interfaces;
                }
            } catch (error) {
                console.error('Failed to load CMTS interfaces:', error);
            }
        },
        
        async searchModems() {
            this.isLoading = true;
            this.searchPerformed = true;
            
            try {
                let url = `${API_BASE}/modems?`;
                
                if (this.searchValue) {
                    url += `search_type=${this.searchType}&search_value=${encodeURIComponent(this.searchValue)}&`;
                }
                if (this.selectedCmts) {
                    url += `cmts=${encodeURIComponent(this.selectedCmts)}&`;
                }
                if (this.selectedInterface) {
                    url += `interface=${encodeURIComponent(this.selectedInterface)}&`;
                }
                
                const response = await fetch(url);
                const data = await response.json();
                
                if (data.status === 'success') {
                    this.modems = data.modems;
                } else {
                    this.showError('Search failed', data.message || 'Unknown error');
                }
            } catch (error) {
                console.error('Search failed:', error);
                this.showError('Search failed', error.message);
            } finally {
                this.isLoading = false;
            }
        },
        
        async getLiveModems() {
            if (!this.selectedCmts) {
                this.showError('Select CMTS', 'Please select a CMTS first');
                return;
            }
            
            this.loadingLiveModems = true;
            this.liveModemSource = '';
            
            try {
                let url = `${API_BASE}/cmts/${encodeURIComponent(this.selectedCmts)}/modems?community=${this.snmpCommunity}&limit=10000`;
                if (this.enrichModems) {
                    url += `&enrich=true&modem_community=${this.snmpCommunityModem}`;
                }
                const response = await fetch(url);
                const data = await response.json();
                
                if (data.status === 'success') {
                    // Transform live modems to match mock data format
                    this.modems = data.modems.map(m => ({
                        mac_address: m.mac_address,
                        ip_address: m.ip_address,
                        status: m.status || 'unknown',
                        name: m.mac_address,  // Use MAC as name for now
                        vendor: m.vendor || 'Unknown',
                        model: m.model || 'N/A',
                        docsis_version: m.docsis_version || 'Unknown',
                        cmts: data.cmts_hostname,
                        cmts_interface: m.cmts_index || 'N/A',
                        software_version: m.software_version || ''
                    }));
                    this.liveModemSource = `Live data from ${data.cmts_hostname} (${data.cmts_ip}) via agent ${data.agent_id} - ${data.count} modems`;
                    this.searchPerformed = true;
                } else {
                    this.showError('Failed to get modems', data.message || 'Unknown error');
                }
            } catch (error) {
                console.error('Failed to get live modems:', error);
                this.showError('Failed to get modems', error.message);
            } finally {
                this.loadingLiveModems = false;
            }
        },
        
        clearFilters() {
            this.searchValue = '';
            this.selectedCmts = '';
            this.selectedInterface = '';
            this.cmtsInterfaces = [];
            this.liveModemSource = '';
            this.searchModems();
        },
        
        async selectModem(modem) {
            this.selectedModem = modem;
            this.systemInfo = null;
            this.dsChannels = [];
            this.usChannels = [];
            this.rxmerData = null;
            this.eventLog = [];
            
            this.currentView = 'modems';
            
            // Load system info automatically
            await this.loadSystemInfo();
        },
        
        async loadSystemInfo() {
            if (!this.selectedModem) return;
            
            this.loadingSystemInfo = true;
            
            try {
                const response = await fetch(`${API_BASE}/modem/${this.selectedModem.mac_address}/system-info`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ community: this.snmpCommunity })
                });
                
                const data = await response.json();
                
                if (data.status === 'success') {
                    this.systemInfo = data.data;
                } else {
                    this.showError('Failed to load system info', data.message);
                }
            } catch (error) {
                console.error('Failed to load system info:', error);
                this.showError('Failed to load system info', error.message);
            } finally {
                this.loadingSystemInfo = false;
            }
        },
        
        async loadChannelStats() {
            if (!this.selectedModem) return;
            
            this.runningTest = true;
            
            try {
                // Load DS channels
                const dsResponse = await fetch(`${API_BASE}/modem/${this.selectedModem.mac_address}/ds-channels`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ community: this.snmpCommunity })
                });
                const dsData = await dsResponse.json();
                
                if (dsData.status === 'success') {
                    this.dsChannels = dsData.data.downstream_ofdm_channels;
                }
                
                // Load US channels
                const usResponse = await fetch(`${API_BASE}/modem/${this.selectedModem.mac_address}/us-channels`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ community: this.snmpCommunity })
                });
                const usData = await usResponse.json();
                
                if (usData.status === 'success') {
                    this.usChannels = usData.data.upstream_ofdma_channels;
                }
                
                this.showSuccess('Channel Stats Loaded', 'Channel statistics have been retrieved successfully.');
                
            } catch (error) {
                console.error('Failed to load channel stats:', error);
                this.showError('Failed to load channel stats', error.message);
            } finally {
                this.runningTest = false;
            }
        },
        
        async runRxmerTest() {
            if (!this.selectedModem) return;
            
            this.runningTest = true;
            
            try {
                const response = await fetch(`${API_BASE}/modem/${this.selectedModem.mac_address}/rxmer`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        community: this.snmpCommunity,
                        channel_ids: [159]
                    })
                });
                
                const data = await response.json();
                
                if (data.status === 'success') {
                    this.rxmerData = data;
                    this.showSuccess('RxMER Measurement Complete', 'RxMER data has been retrieved successfully.');
                    
                    // Draw charts after Vue updates DOM
                    this.$nextTick(() => {
                        this.drawRxmerCharts();
                    });
                } else {
                    this.showError('RxMER Measurement Failed', data.message);
                }
            } catch (error) {
                console.error('RxMER measurement failed:', error);
                this.showError('RxMER Measurement Failed', error.message);
            } finally {
                this.runningTest = false;
            }
        },
        
        async runSpectrumTest() {
            if (!this.selectedModem) return;
            
            this.runningTest = true;
            
            try {
                const response = await fetch(`${API_BASE}/modem/${this.selectedModem.mac_address}/spectrum`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ community: this.snmpCommunity })
                });
                
                const data = await response.json();
                
                if (data.status === 'success') {
                    this.spectrumData = data;
                    this.showSuccess('Spectrum Analysis Complete', 'Spectrum data has been retrieved successfully.');
                } else {
                    this.showError('Spectrum Analysis Failed', data.message);
                }
            } catch (error) {
                console.error('Spectrum analysis failed:', error);
                this.showError('Spectrum Analysis Failed', error.message);
            } finally {
                this.runningTest = false;
            }
        },
        
        async loadEventLog() {
            if (!this.selectedModem) return;
            
            this.runningTest = true;
            
            try {
                const response = await fetch(`${API_BASE}/modem/${this.selectedModem.mac_address}/event-log`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ community: this.snmpCommunity })
                });
                
                const data = await response.json();
                
                if (data.status === 'success') {
                    this.eventLog = data.data.events;
                    this.showSuccess('Event Log Loaded', `${data.data.events.length} events retrieved.`);
                } else {
                    this.showError('Failed to load event log', data.message);
                }
            } catch (error) {
                console.error('Failed to load event log:', error);
                this.showError('Failed to load event log', error.message);
            } finally {
                this.runningTest = false;
            }
        },
        
        quickPing(modem) {
            // Simulate a quick connectivity check
            Swal.fire({
                title: 'Checking Connectivity...',
                text: `Pinging ${modem.ip_address}`,
                timer: 1500,
                timerProgressBar: true,
                didOpen: () => {
                    Swal.showLoading();
                }
            }).then(() => {
                if (modem.status === 'online') {
                    this.showSuccess('Modem Reachable', `${modem.ip_address} responded successfully.`);
                } else {
                    this.showError('Modem Unreachable', `${modem.ip_address} did not respond.`);
                }
            });
        },
        
        // ============== Chart Drawing ==============
        
        drawRxmerCharts() {
            if (!this.rxmerData) return;
            
            this.rxmerData.data.rxmer_measurements.forEach(meas => {
                const canvasId = `rxmer-chart-${meas.channel_id}`;
                const canvas = document.getElementById(canvasId);
                
                if (!canvas) return;
                
                // Destroy existing chart if any
                if (this.charts[canvasId]) {
                    this.charts[canvasId].destroy();
                }
                
                const ctx = canvas.getContext('2d');
                
                const labels = meas.subcarrier_samples.map(s => s.subcarrier_index);
                const data = meas.subcarrier_samples.map(s => s.mer_db);
                
                this.charts[canvasId] = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'MER (dB)',
                            data: data,
                            borderColor: 'rgb(13, 110, 253)',
                            backgroundColor: 'rgba(13, 110, 253, 0.1)',
                            fill: true,
                            tension: 0.1,
                            pointRadius: 0
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                display: false
                            }
                        },
                        scales: {
                            x: {
                                title: {
                                    display: true,
                                    text: 'Subcarrier Index'
                                }
                            },
                            y: {
                                title: {
                                    display: true,
                                    text: 'MER (dB)'
                                },
                                min: 25,
                                max: 50
                            }
                        }
                    }
                });
            });
        },
        
        // ============== Formatting Helpers ==============
        
        formatFreq(hz) {
            if (hz >= 1000000000) {
                return (hz / 1000000000).toFixed(1) + ' GHz';
            } else if (hz >= 1000000) {
                return (hz / 1000000).toFixed(1) + ' MHz';
            } else {
                return (hz / 1000).toFixed(1) + ' kHz';
            }
        },
        
        formatEventTime(isoString) {
            const date = new Date(isoString);
            return date.toLocaleString();
        },
        
        getMerBadgeClass(mer) {
            if (mer >= 40) return 'bg-success';
            if (mer >= 35) return 'bg-primary';
            if (mer >= 30) return 'bg-warning';
            return 'bg-danger';
        },
        
        getEventBadgeClass(level) {
            const classes = {
                'notice': 'bg-info',
                'warning': 'bg-warning text-dark',
                'error': 'bg-danger',
                'critical': 'bg-danger'
            };
            return classes[level] || 'bg-secondary';
        },
        
        getEventRowClass(level) {
            const classes = {
                'warning': 'event-warning',
                'error': 'event-error',
                'critical': 'event-critical'
            };
            return classes[level] || '';
        },
        
        // ============== Notifications ==============
        
        showSuccess(title, text) {
            Swal.fire({
                icon: 'success',
                title: title,
                text: text,
                toast: true,
                position: 'top-end',
                showConfirmButton: false,
                timer: 3000,
                timerProgressBar: true
            });
        },
        
        showError(title, text) {
            Swal.fire({
                icon: 'error',
                title: title,
                text: text,
                toast: true,
                position: 'top-end',
                showConfirmButton: false,
                timer: 5000,
                timerProgressBar: true
            });
        }
    }
}).mount('#app');
