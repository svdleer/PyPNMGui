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
            pypnmHealthy: false,
            
            // Loading state
            isLoading: false,
            loadingSystemInfo: false,
            runningTest: false,
            
            // Search parameters
            searchType: 'ip',
            searchValue: '',
            snmpCommunity: 'Z1gg0@LL',
            snmpCommunityRW: 'Z1gg0Sp3c1@l',
            snmpCommunityModem: 'z1gg0m0n1t0r1ng',
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
            channelStats: null,  // Enhanced channel stats with profiles
            rxmerData: null,
            spectrumData: null,
            fecData: null,
            preEqData: null,
            eventLog: [],
            
            // PNM Measurement selection
            pnmMeasurementType: 'rxmer',
            pnmOutputType: 'archive',  // archive (with plots) or json
            showRawData: false,
            selectedMeasurementData: null,
            
            // Upstream PNM (CMTS-side)
            upstreamInterfaces: {
                loading: false,
                scqamChannels: [],   // SC-QAM upstream channels [{ifindex, channel_id, frequency_mhz}]
                ofdmaChannels: [],   // OFDMA upstream channels [{ifindex, index}]
                rfPorts: [],    // us-conn RF ports for UTSC [{ifindex, description}]
                allRfPorts: [],  // All us-conn RF ports
                modemRfPort: null  // Detected RF port for the modem
            },
            utscConfig: {
                triggerMode: 2,  // 2=FreeRunning (timed captures), 6=CM_MAC (per-transmission), 5=IdleSID
                centerFreqMhz: 50,
                spanMhz: 80,
                numBins: 3200,
                rfPortIfindex: null,
                repeatPeriodMs: 1000,  // 1000ms (1 second) - max on E6000, slower but more reliable
                freerunDurationMs: 55000,  // 55 seconds (E6000 max is 60s for FreeRunning mode)
                triggerCount: 10  // Max 10 on E6000 (ignored in FreeRunning mode per docs)
            },
            usRxmerConfig: {
                ofdmaIfindex: null,
                preEq: true
            },
            runningUtsc: false,
            runningUsRxmer: false,
            utscStatus: null,
            usRxmerStatus: null,
            utscSpectrumData: null,
            utscPlotImage: null,  // Matplotlib plot data
            usRxmerSpectrumData: null,
            utscChartInstance: null,
            usRxmerChartInstance: null,
            utscLiveMode: false,
            utscLiveInterval: null,
            utscWebSocket: null,  // WebSocket for live UTSC streaming
            utscRefreshRate: 500,  // 0.5 seconds between updates (streaming rate)
            utscDuration: 60,  // Duration in seconds
            utscBufferSize: 0,  // Current buffer size from backend
            utscInteractive: true,  // Always use SciChart interactive mode
            utscSciChart: null,  // SciChart instance
            utscSciChartSeries: null,  // SciChart data series
            utscLastUpdateTime: 0,  // Throttle rapid updates
            utscUpdateThrottle: 100,  // Min 100ms between updates
            
            // Housekeeping
            housekeepingDays: 7,
            housekeepingDryRun: true,
            housekeepingResult: null,
            
            // Live modem loading
            loadingLiveModems: false,
            liveModemSource: '',
            enrichModems: true,
            
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
        // ============== Utility Methods ==============
        
        formatPlotTitle(filename) {
            // Convert filename to readable title
            // Example: "90324bc81037_ubc1318zg_1768641563_34_rxmer.png" -> "RxMER - Channel 34"
            const cleanName = filename.replace(/\.png$/i, '');
            const parts = cleanName.split('_');
            
            // Extract meaningful parts
            if (cleanName.includes('rxmer')) {
                const channel = parts.find(p => p.match(/^\d{1,3}$/) && parseInt(p) < 200);
                return channel ? `RxMER - Channel ${channel}` : 'RxMER';
            } else if (cleanName.includes('modulation_count')) {
                const channel = parts.find(p => p.match(/^\d{1,3}$/) && parseInt(p) < 200);
                return channel ? `Modulation Profile - Channel ${channel}` : 'Modulation Profile';
            } else if (cleanName.includes('signal_aggregate')) {
                return 'Signal Aggregate (All Channels)';
            } else if (cleanName.includes('channel_est')) {
                return 'Channel Estimation Coefficients';
            } else if (cleanName.includes('spectrum')) {
                return 'Spectrum Analyzer';
            }
            
            // Fallback: clean up the filename
            return cleanName.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        },
        
        // ============== API Calls ==============
        
        async checkApiHealth() {
            try {
                const response = await fetch(`${API_BASE}/health`);
                const data = await response.json();
                this.apiStatus = data.status;
                
                // Also check PyPNM health
                try {
                    const pypnmResponse = await fetch(`${API_BASE}/pypnm/health`);
                    const pypnmData = await pypnmResponse.json();
                    this.pypnmHealthy = pypnmData.pypnm_healthy || false;
                } catch (e) {
                    this.pypnmHealthy = false;
                }
            } catch (error) {
                console.error('API health check failed:', error);
                this.apiStatus = 'mock';
                this.pypnmHealthy = false;
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
                        cmts_ip: data.cmts_ip,  // For upstream PNM
                        cmts_community: data.cmts_community || 'Z1gg0Sp3c1@l',  // SNMP write community for PNM
                        tftp_ip: data.tftp_ip || data.cmts_ip,  // TFTP server IP
                        cmts_interface: m.interface || m.cmts_index || 'N/A',
                        software_version: m.software_version || ''
                    }));
                    const cacheInfo = data.cached ? ' (cached)' : '';
                    const enrichInfo = data.enriched ? ' [enriched]' : (data.enriching ? ' [enriching in background...]' : '');
                    this.liveModemSource = `Live data from ${data.cmts_hostname} (${data.cmts_ip}) via agent ${data.agent_id} - ${data.count} modems${cacheInfo}${enrichInfo}`;
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
            this.channelStats = null;
            this.rxmerData = null;
            this.eventLog = [];
            this.selectedMeasurementData = null;
            this.showRawData = false;
            
            // Reset upstream interfaces
            this.upstreamInterfaces = { loading: false, scqamChannels: [], ofdmaChannels: [], rfPorts: [], allRfPorts: [], modemRfPort: null };
            this.utscConfig.rfPortIfindex = null;
            this.usRxmerConfig.ofdmaIfindex = null;
            
            this.currentView = 'modems';
            
            // Load system info and channel stats automatically
            try {
                const promises = [
                    this.loadSystemInfo(),
                    this.loadChannelStats()
                ];
                
                // Also load upstream interfaces if CMTS IP is available (for upstream PNM)
                if (modem.cmts_ip) {
                    promises.push(this.loadUpstreamInterfaces());
                }
                
                await Promise.all(promises);
            } catch (error) {
                console.error('Error loading modem data:', error);
            }
        },
        
        async loadSystemInfo() {
            if (!this.selectedModem) return;
            
            this.loadingSystemInfo = true;
            
            try {
                // Use PyPNM API for channel stats
                const response = await fetch(`${API_BASE}/pypnm/modem/${this.selectedModem.mac_address}/channel-stats`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        modem_ip: this.selectedModem.ip_address,
                        community: this.snmpCommunityModem || 'z1gg0m0n1t0r1ng'
                    })
                });
                
                const data = await response.json();
                
                if (data.downstream || data.upstream) {
                    // Transform PyPNM response to systemInfo format
                    this.systemInfo = {
                        downstream: this.transformChannelData(data.downstream),
                        upstream: this.transformUpstreamData(data.upstream),
                        timestamp: new Date().toISOString()
                    };
                    
                    // Draw charts after Vue updates DOM
                    this.$nextTick(() => {
                        this.drawDsChannelChart();
                        this.drawUsChannelChart();
                    });
                } else if (data.error) {
                    this.showError('Failed to load system info', data.error || data.message);
                } else {
                    // If no data, try to show what we have
                    this.systemInfo = {
                        downstream: [],
                        upstream: [],
                        timestamp: new Date().toISOString()
                    };
                    this.showError('No channel data', 'Could not retrieve channel information from modem');
                }
            } catch (error) {
                console.error('Failed to load system info:', error);
                this.showError('Failed to load system info', error.message);
            } finally {
                this.loadingSystemInfo = false;
            }
        },
        
        // Helper to transform PyPNM channel data
        transformChannelData(dsData) {
            if (!dsData) return [];
            
            // Handle SC-QAM data from PyPNM response format
            const scqam = dsData.scqam || {};
            const channels = [];
            
            // PyPNM returns .results array
            const results = scqam.results || [];
            if (Array.isArray(results)) {
                results.forEach((ch, idx) => {
                    const entry = ch.entry || ch;
                    channels.push({
                        channel_id: ch.channel_id || entry.docsIfDownChannelId || idx + 1,
                        frequency_mhz: entry.docsIfDownChannelFrequency ? entry.docsIfDownChannelFrequency / 1000000 : 0,
                        power_dbmv: entry.docsIfDownChannelPower || 0,
                        snr_db: entry.docsIf3SignalQualityExtRxMER ? entry.docsIf3SignalQualityExtRxMER / 10 : 0
                    });
                });
            }
            
            return channels;
        },
        
        // Helper to transform PyPNM channel data (SC-QAM + OFDM)
        transformChannelData(dsData) {
            if (!dsData) return [];
            
            const channels = [];
            
            // Handle SC-QAM data from PyPNM response format
            const scqam = dsData.scqam || {};
            const scqamResults = scqam.results || [];
            if (Array.isArray(scqamResults)) {
                scqamResults.forEach((ch, idx) => {
                    const entry = ch.entry || ch;
                    channels.push({
                        channel_id: ch.channel_id || entry.docsIfDownChannelId || idx + 1,
                        frequency_mhz: entry.docsIfDownChannelFrequency ? entry.docsIfDownChannelFrequency / 1000000 : 0,
                        power_dbmv: entry.docsIfDownChannelPower || 0,
                        snr_db: entry.docsIf3SignalQualityExtRxMER ? entry.docsIf3SignalQualityExtRxMER / 10 : 0,
                        type: 'SC-QAM'
                    });
                });
            }
            
            // Handle OFDM data (DOCSIS 3.1) - may come as channels array or results
            const ofdm = dsData.ofdm || {};
            const ofdmChannels = ofdm.channels || ofdm.results || [];
            if (Array.isArray(ofdmChannels)) {
                ofdmChannels.forEach((ch, idx) => {
                    const entry = ch.entry || ch;
                    // Get values - prefer pre-processed channel data, fallback to raw entry
                    const plcFreq = ch.plc_freq_mhz || (entry.docsIf31CmDsOfdmChanPlcFreq ? entry.docsIf31CmDsOfdmChanPlcFreq / 1000000 : 0);
                    const numSubcarriers = ch.num_subcarriers || entry.docsIf31CmDsOfdmChanNumActiveSubcarriers || 0;
                    const subcarrierSpacing = entry.docsIf31CmDsOfdmChanSubcarrierSpacing || 50000;
                    const bw = ch.bandwidth_mhz || (numSubcarriers * subcarrierSpacing) / 1000000;
                    const power = ch.power_dbmv !== undefined ? ch.power_dbmv : (entry.docsIf31CmDsOfdmChannelPower ? entry.docsIf31CmDsOfdmChannelPower / 10 : null);
                    const mer = ch.mer_db !== undefined ? ch.mer_db : (entry.docsIf31CmDsOfdmChanMer ? entry.docsIf31CmDsOfdmChanMer / 10 : null);
                    
                    channels.push({
                        channel_id: ch.channel_id || entry.docsIf31CmDsOfdmChanChannelId || 100 + idx,
                        frequency_mhz: ch.frequency_mhz || plcFreq,
                        plc_freq_mhz: plcFreq,
                        bandwidth_mhz: bw,
                        power_dbmv: power,
                        snr_db: mer,
                        mer_db: mer,
                        num_subcarriers: numSubcarriers,
                        subcarrier_spacing_khz: ch.subcarrier_spacing_khz || (subcarrierSpacing / 1000),
                        profiles: ch.profiles || [],
                        active_profiles: ch.active_profiles || (ch.profiles ? ch.profiles.length : 0),
                        is_partial: ch.is_partial || false,
                        modulation: ch.modulation || null,
                        type: 'OFDM'
                    });
                });
            }
            
            return channels;
        },
        
        transformUpstreamData(usData) {
            if (!usData) return [];
            
            const channels = [];
            
            // Handle ATDMA data
            const atdma = usData.atdma || {};
            const atdmaResults = atdma.results || [];
            if (Array.isArray(atdmaResults)) {
                atdmaResults.forEach((ch, idx) => {
                    const entry = ch.entry || ch;
                    const freq = entry.docsIfUpChannelFrequency || 0;
                    channels.push({
                        channel_id: ch.channel_id || entry.docsIfUpChannelId || idx + 1,
                        frequency_mhz: freq ? freq / 1000000 : null,
                        power_dbmv: entry.docsIf3CmStatusUsTxPower || 0,
                        type: 'ATDMA'
                    });
                });
            }
            
            // Handle OFDMA data (DOCSIS 3.1) - may come as channels array or results
            const ofdma = usData.ofdma || {};
            const ofdmaChannels = ofdma.channels || ofdma.results || [];
            if (Array.isArray(ofdmaChannels)) {
                ofdmaChannels.forEach((ch, idx) => {
                    const entry = ch.entry || ch;
                    // Get values - prefer pre-processed channel data
                    const freq = ch.frequency_mhz || (entry.docsIf31CmUsOfdmaChanSubcarrierZeroFreq ? entry.docsIf31CmUsOfdmaChanSubcarrierZeroFreq / 1000000 : 0);
                    const numSubcarriers = ch.num_subcarriers || entry.docsIf31CmUsOfdmaChanNumActiveSubcarriers || 0;
                    const subcarrierSpacing = entry.docsIf31CmUsOfdmaChanSubcarrierSpacing || 50;  // in kHz
                    const bw = ch.bandwidth_mhz || (numSubcarriers * subcarrierSpacing) / 1000;
                    const power = ch.tx_power !== undefined ? ch.tx_power : (entry.docsIf31CmUsOfdmaChanTxPower || null);
                    
                    channels.push({
                        channel_id: ch.channel_id || entry.docsIf31CmUsOfdmaChanChannelId || 100 + idx,
                        frequency_mhz: freq,
                        bandwidth_mhz: bw,
                        power_dbmv: power,
                        num_subcarriers: numSubcarriers,
                        profiles: ch.profiles || [],
                        type: 'OFDMA'
                    });
                });
            }
            
            return channels;
        },
        
        async loadChannelStats() {
            if (!this.selectedModem) return;
            
            this.runningTest = true;
            
            try {
                // Use PyPNM API for channel stats
                const response = await fetch(`${API_BASE}/pypnm/modem/${this.selectedModem.mac_address}/channel-stats`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        modem_ip: this.selectedModem.ip_address,
                        community: this.snmpCommunityModem || 'z1gg0m0n1t0r1ng'
                    })
                });
                
                const data = await response.json();
                
                // Process DS OFDM channels if available
                if (data.downstream && data.downstream.ofdm) {
                    const ofdm = data.downstream.ofdm;
                    // PyPNM returns .results array
                    const results = ofdm.results || ofdm.channels || [];
                    if (Array.isArray(results) && results.length > 0) {
                        this.dsChannels = results.map((ch, idx) => {
                            const entry = ch.entry || ch;
                            return {
                                channel_id: ch.channel_id || entry.docsIf31CmDsOfdmChanChannelId || idx + 1,
                                frequency_start_hz: entry.docsIf31CmDsOfdmChanPlcFreq || 0,
                                frequency_end_hz: (entry.docsIf31CmDsOfdmChanPlcFreq || 0) + 192000000,
                                active_subcarriers: entry.docsIf31CmDsOfdmChanNumActiveSubcarriers || 0,
                                power_dbmv: entry.docsIf31CmDsOfdmChannelPower || 0,
                                snr_db: entry.docsIf31CmDsOfdmChanMer ? entry.docsIf31CmDsOfdmChanMer / 10 : 0,
                                mer_db: entry.docsIf31CmDsOfdmChanMer ? entry.docsIf31CmDsOfdmChanMer / 10 : 0
                            };
                        });
                    }
                }
                
                // Process US OFDMA channels if available
                if (data.upstream && data.upstream.ofdma) {
                    const ofdma = data.upstream.ofdma;
                    // PyPNM returns .results array
                    const results = ofdma.results || ofdma.channels || [];
                    if (Array.isArray(results) && results.length > 0) {
                        this.usChannels = results.map((ch, idx) => {
                            const entry = ch.entry || ch;
                            return {
                                channel_id: ch.channel_id || entry.docsIf31CmUsOfdmaChanChannelId || idx + 1,
                                frequency_start_hz: entry.docsIf31CmUsOfdmaChanFirstActiveSubcarrierNum * 50000 || 0,
                                frequency_end_hz: entry.docsIf31CmUsOfdmaChanLastActiveSubcarrierNum * 50000 || 0,
                                active_subcarriers: entry.docsIf31CmUsOfdmaChanNumActiveSubcarriers || 0,
                                power_dbmv: entry.docsIf31CmUsOfdmaChanTxPower ? entry.docsIf31CmUsOfdmaChanTxPower / 10 : 0,
                                timing_offset: entry.docsIf31CmUsOfdmaChanT3Timeouts || 0
                            };
                        });
                    }
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
            return this.runPnmMeasurement('rxmer');
        },
        
        async runSpectrumTest() {
            return this.runPnmMeasurement('spectrum');
        },
        
        async runFecTest() {
            return this.runPnmMeasurement('fec_summary');
        },
        
        async runPreEqTest() {
            return this.runPnmMeasurement('us_pre_eq');
        },
        
        async runChannelEstimation() {
            return this.runPnmMeasurement('channel_estimation');
        },
        
        async runModulationProfile() {
            return this.runPnmMeasurement('modulation_profile');
        },
        
        async runHistogram() {
            return this.runPnmMeasurement('histogram');
        },
        
        async runConstellation() {
            return this.runPnmMeasurement('constellation');
        },
        
        // ============== Upstream PNM Methods (CMTS-side) ==============
        
        async loadUpstreamInterfaces() {
            if (!this.selectedModem || !this.selectedModem.cmts_ip) {
                return;
            }
            
            this.upstreamInterfaces.loading = true;
            console.log('[UTSC] Starting fast RF port discovery...');
            
            try {
                // Use the new fast discovery endpoint
                const response = await fetch(`/api/pypnm/upstream/discover-rf-port/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip
                    })
                });
                
                const result = await response.json();
                if (result.success) {
                    // Set the discovered RF port
                    this.utscConfig.rfPortIfindex = result.rf_port_ifindex;
                    
                    // Store in upstreamInterfaces for UI display
                    this.upstreamInterfaces.rfPorts = [{
                        ifindex: result.rf_port_ifindex,
                        description: result.rf_port_description,
                        name: result.rf_port_description
                    }];
                    this.upstreamInterfaces.modemRfPort = {
                        ifindex: result.rf_port_ifindex,
                        description: result.rf_port_description
                    };
                    
                    console.log(`[UTSC] Discovered RF port: ${result.rf_port_ifindex} (${result.rf_port_description})`);
                    console.log(`[UTSC] CM Index: ${result.cm_index}, US Channels: ${result.us_channels?.length || 0}`);
                    
                    this.$toast?.success(`RF port discovered: ${result.rf_port_description}`);
                } else {
                    console.error('[UTSC] RF port discovery failed:', result.error);
                    this.$toast?.warning(result.error || 'RF port discovery failed');
                }
            } catch (error) {
                console.error('[UTSC] Discovery error:', error);
                this.$toast?.error('RF port discovery failed: ' + error.message);
            } finally {
                this.upstreamInterfaces.loading = false;
            }
        },
        
        async configureUtsc() {
            if (!this.selectedModem || !this.selectedModem.cmts_ip) {
                this.$toast?.error('No CMTS IP available for this modem');
                return;
            }
            
            if (!this.utscConfig.rfPortIfindex) {
                this.$toast?.error('RF Port ifIndex is required');
                return;
            }
            
            try {
                const response = await fetch(`/api/pypnm/upstream/utsc/configure/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip,
                        rf_port_ifindex: this.utscConfig.rfPortIfindex,
                        trigger_mode: this.utscConfig.triggerMode,
                        center_freq_hz: this.utscConfig.centerFreqMhz * 1000000,
                        span_hz: this.utscConfig.spanMhz * 1000000,
                        num_bins: this.utscConfig.numBins,
                        output_format: 2,  // fftPower
                        repeat_period_ms: this.utscConfig.repeatPeriodMs,
                        freerun_duration_ms: this.utscConfig.freerunDurationMs,
                        community: this.selectedModem.cmts_community || 'Z1gg0@LL'
                    })
                });
                
                const result = await response.json();
                if (result.success) {
                    this.$toast?.success('UTSC configured successfully');
                } else {
                    this.$toast?.error(result.error || 'Failed to configure UTSC');
                }
            } catch (error) {
                console.error('Configure UTSC error:', error);
                this.$toast?.error('Failed to configure UTSC');
            }
        },
        
        // Unified Start/Stop for UTSC live monitoring
        async startUtscLive() {
            if (this.utscLiveMode) {
                // Stop mode
                this.stopUtscLive();
                return;
            }
            
            // Start mode
            if (!this.selectedModem) {
                this.$toast?.warning('Please select a modem first');
                return;
            }
            if (!this.utscConfig.rfPortIfindex) {
                this.$toast?.warning('Please select an RF Port');
                return;
            }
            
            // Initialize chart first
            // Show buffering message
            this.$toast?.info('Initializing UTSC live stream...');
            
            // Set utscLiveMode first so the chart div becomes visible in DOM
            this.utscLiveMode = true;
            
            // Now wait for Vue to render the chart div
            console.log('[UTSC] Starting live mode...');
            await this.ensureSciChartLoaded();
            await this.$nextTick();
            await new Promise(resolve => setTimeout(resolve, 300));
            
            if (!this.utscSciChart) {
                await this.initUtscSciChart();
            }
            
            if (!this.utscSciChart || !this.utscSciChartSeries) {
                console.error('[UTSC] SciChart failed to initialize');
                this.$toast?.error('Failed to initialize chart');
                this.utscLiveMode = false;
                return;
            }
            
            // Configure and start UTSC on CMTS first
            console.log('[UTSC] Chart ready, configuring UTSC on CMTS...');
            this.$toast?.info('Configuring UTSC measurement on CMTS...');
            
            const cmtsIp = this.selectedModem.cmts_ip;
            if (!cmtsIp) {
                this.$toast?.error('CMTS IP not available');
                this.utscLiveMode = false;
                return;
            }
            
            try {
                const response = await fetch(`/api/pypnm/upstream/utsc/start/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: cmtsIp,
                        rf_port_ifindex: this.utscConfig.rfPortIfindex,
                        community: this.selectedModem.cmts_community || 'Z1gg0Sp3c1@l',
                        tftp_ip: this.selectedModem.tftp_ip,
                        repeat_period_ms: this.utscConfig.repeatPeriodMs || 1000,
                        freerun_duration_ms: this.utscConfig.freerunDurationMs || 55000,
                        trigger_count: this.utscConfig.triggerCount || 10
                    })
                });
                
                const result = await response.json();
                if (!result.success) {
                    this.$toast?.error(result.error || 'Failed to configure UTSC');
                    this.utscLiveMode = false;
                    return;
                }
                
                console.log('[UTSC] UTSC configured, starting WebSocket stream...');
                this.$toast?.info('UTSC configured, starting live stream...');
                
                // Wait for initial files to be generated
                await new Promise(resolve => setTimeout(resolve, 2000));
                
                // Now start WebSocket streaming
                this.startUtscWebSocket();
            } catch (error) {
                console.error('[UTSC] Failed to configure UTSC:', error);
                this.$toast?.error('Failed to configure UTSC: ' + error.message);
                this.utscLiveMode = false;
                return;
            }
            
            // Wait for WebSocket to connect (max 5 seconds)
            const wsReady = await new Promise(resolve => {
                let attempts = 0;
                const checkWs = setInterval(() => {
                    attempts++;
                    if (this.utscWebSocket && this.utscWebSocket.readyState === WebSocket.OPEN) {
                        clearInterval(checkWs);
                        resolve(true);
                    } else if (attempts > 50) {  // 5 seconds
                        clearInterval(checkWs);
                        resolve(false);
                    }
                }, 100);
            });
            
            if (!wsReady) {
                console.error('[UTSC] WebSocket failed to connect');
                this.$toast?.error('Failed to connect WebSocket');
                this.stopUtscWebSocket();
                this.utscLiveMode = false;
                return;
            }
            
            // Now start the UTSC measurement (configure + start)
            await this.startUtsc();
            
            this.$toast?.success('Live monitoring started - buffering data...');
            
            // Auto-restart UTSC measurement every 50 seconds
            this.utscAutoRestartInterval = setInterval(async () => {
                if (this.utscLiveMode && !this.runningUtsc) {
                    console.log('[UTSC] Auto-restarting measurement...');
                    await this.startUtsc();
                }
            }, 50000);
        },
        
        stopUtscLive() {
            console.log('[UTSC] Stopping live mode...');
            this.utscLiveMode = false;
            this.runningUtsc = false;
            this.$toast?.info('Live monitoring stopped');
            this.stopUtscWebSocket();
            
            // Also stop UTSC on CMTS (don't wait for result)
            if (this.selectedModem && this.selectedModem.cmts_ip && this.utscConfig.rfPortIfindex) {
                this.stopUtsc();
            }
            
            // Clear auto-restart interval
            if (this.utscAutoRestartInterval) {
                clearInterval(this.utscAutoRestartInterval);
                this.utscAutoRestartInterval = null;
            }
            
            // Reset buffer size display
            this.utscBufferSize = 0;
        },
        
        async startUtsc() {
            if (!this.selectedModem) {
                this.$toast?.warning('Please select a modem first');
                return;
            }
            if (!this.utscConfig.rfPortIfindex) {
                this.$toast?.warning('Please select an RF Port');
                return;
            }
            
            // Get CMTS IP from modem or fallback to selectedCmts
            const cmtsIp = this.selectedModem.cmts_ip || this.selectedCmts;
            if (!cmtsIp) {
                this.$toast?.error('CMTS IP not available');
                return;
            }
            
            this.runningUtsc = true;
            this.utscStatus = null;
            
            try {
                // Show progress message
                this.$toast?.info('UTSC capture in progress - this may take up to 2 minutes...');
                
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), 180000); // 3 minute timeout
                
                const response = await fetch(`/api/pypnm/upstream/utsc/start/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: cmtsIp,
                        rf_port_ifindex: this.utscConfig.rfPortIfindex,
                        community: this.selectedModem.cmts_community || 'Z1gg0Sp3c1@l',
                        tftp_ip: this.selectedModem.tftp_ip,
                        repeat_period_ms: this.utscConfig.repeatPeriodMs || 1000,
                        freerun_duration_ms: this.utscConfig.freerunDurationMs || 55000,  // 55s max for E6000
                        trigger_count: this.utscConfig.triggerCount || 10  // Max 10 on E6000
                    }),
                    signal: controller.signal
                });
                
                clearTimeout(timeoutId);
                
                const result = await response.json();
                if (result.success) {
                    const message = result.data?.message || 'UTSC completed';
                    this.$toast?.info(`${message} - fetching spectrum data...`);
                    
                    // Wait a moment for files to be written, then fetch the data
                    await new Promise(resolve => setTimeout(resolve, 2000));
                    await this.fetchUtscData();
                    
                    // Measurement started successfully, reset runningUtsc so we can start again
                    this.runningUtsc = false;
                } else {
                    this.$toast?.error(result.error || 'Failed to start UTSC');
                    this.runningUtsc = false;
                }
            } catch (error) {
                console.error('Start UTSC error:', error);
                this.$toast?.error('Failed to start UTSC');
                this.runningUtsc = false;
            }
        },
        
        async stopUtsc() {
            if (!this.selectedModem || !this.selectedModem.cmts_ip || !this.utscConfig.rfPortIfindex) {
                this.$toast?.warning('No active UTSC session to stop');
                return;
            }
            
            try {
                this.$toast?.info('Stopping UTSC capture...');
                
                const response = await fetch(`/api/pypnm/upstream/utsc/stop/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip,
                        rf_port_ifindex: this.utscConfig.rfPortIfindex,
                        community: this.selectedModem.cmts_community || 'Z1gg0Sp3c1@l'
                    })
                });
                
                const result = await response.json();
                this.runningUtsc = false;
                
                if (result.success) {
                    this.$toast?.success('UTSC capture stopped');
                    // Stop live monitoring
                    if (this.utscLiveMode) {
                        this.utscLiveMode = false;
                        this.stopUtscWebSocket();
                    }
                } else {
                    this.$toast?.error(result.message || 'Failed to stop UTSC');
                }
            } catch (error) {
                console.error('Stop UTSC error:', error);
                this.$toast?.error('Failed to stop UTSC');
                this.runningUtsc = false;
            }
        },
        
        async pollUtscStatus() {
            if (!this.runningUtsc) return;
            
            try {
                const response = await fetch(`/api/pypnm/upstream/utsc/status/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip,
                        rf_port_ifindex: this.utscConfig.rfPortIfindex,
                        community: this.selectedModem.cmts_community || 'Z1gg0@LL'
                    })
                });
                
                const result = await response.json();
                this.utscStatus = result;
                
                if (result.is_ready) {
                    this.runningUtsc = false;
                    this.$toast?.success('UTSC capture complete - fetching data...');
                    // Auto-fetch spectrum data
                    await this.fetchUtscData();
                } else if (result.is_error) {
                    this.runningUtsc = false;
                    this.$toast?.error('UTSC test failed');
                } else if (result.is_busy) {
                    // Continue polling
                    setTimeout(() => this.pollUtscStatus(), 2000);
                }
            } catch (error) {
                console.error('Poll UTSC status error:', error);
                this.runningUtsc = false;
            }
        },
        
        async startUsRxmer() {
            if (!this.selectedModem || !this.selectedModem.cmts_ip || !this.usRxmerConfig.ofdmaIfindex) {
                this.$toast?.error('CMTS IP and OFDMA ifIndex required');
                return;
            }
            
            this.runningUsRxmer = true;
            this.usRxmerStatus = null;
            
            try {
                const response = await fetch(`/api/pypnm/upstream/rxmer/start/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip,
                        ofdma_ifindex: this.usRxmerConfig.ofdmaIfindex,
                        pre_eq: this.usRxmerConfig.preEq,
                        community: this.selectedModem.cmts_community || 'Z1gg0@LL'
                    })
                });
                
                const result = await response.json();
                if (result.success) {
                    this.$toast?.success('US RxMER measurement started');
                    this.pollUsRxmerStatus();
                } else {
                    this.$toast?.error(result.error || 'Failed to start US RxMER');
                    this.runningUsRxmer = false;
                }
            } catch (error) {
                console.error('Start US RxMER error:', error);
                this.$toast?.error('Failed to start US RxMER');
                this.runningUsRxmer = false;
            }
        },
        
        async pollUsRxmerStatus() {
            if (!this.runningUsRxmer) return;
            
            try {
                const response = await fetch(`/api/pypnm/upstream/rxmer/status/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip,
                        ofdma_ifindex: this.usRxmerConfig.ofdmaIfindex,
                        community: this.selectedModem.cmts_community || 'Z1gg0@LL'
                    })
                });
                
                const result = await response.json();
                this.usRxmerStatus = result;
                
                if (result.is_ready) {
                    this.runningUsRxmer = false;
                    this.$toast?.success('US RxMER complete - fetching data...');
                    // Auto-fetch RxMER data
                    await this.fetchUsRxmerData();
                } else if (result.is_error) {
                    this.runningUsRxmer = false;
                    this.$toast?.error('US RxMER measurement failed');
                } else if (result.is_busy) {
                    setTimeout(() => this.pollUsRxmerStatus(), 2000);
                }
            } catch (error) {
                console.error('Poll US RxMER status error:', error);
                this.runningUsRxmer = false;
            }
        },
        
        async fetchUtscData() {
            if (!this.selectedModem || !this.selectedModem.cmts_ip) {
                this.runningUtsc = false;
                return;
            }
            
            try {
                const response = await fetch(`/api/pypnm/upstream/utsc/data/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip,
                        rf_port_ifindex: this.utscConfig.rfPortIfindex,
                        community: this.selectedModem.cmts_community || 'Z1gg0Sp3c1@l'
                    })
                });
                
                const result = await response.json();
                console.log('UTSC data response:', result);
                
                if (result.success && result.data) {
                    console.log('[UTSC] Success, updating data, plot exists:', !!result.plot, 'has data:', !!result.plot?.data);
                    this.utscSpectrumData = result.data;
                    // Force Vue reactivity by creating new object reference
                    this.utscPlotImage = result.plot ? { ...result.plot, _timestamp: Date.now() } : null;
                    console.log('[UTSC] Updated utscPlotImage:', !!this.utscPlotImage, 'timestamp:', this.utscPlotImage?._timestamp);
                    
                    // Initialize SciChart immediately when data first loads
                    if (!this.utscSciChart) {
                        console.log('[UTSC] First data received, initializing SciChart...');
                        this.$nextTick(async () => {
                            await this.ensureSciChartLoaded();
                            await new Promise(resolve => setTimeout(resolve, 100));
                            await this.initUtscSciChart();
                            // Display initial data
                            if (result.data.raw_data) {
                                this.updateUtscSciChart(result.data.raw_data);
                            }
                        });
                    }
                    
                    if (!this.utscLiveMode) {
                        this.$toast?.success('UTSC spectrum data loaded');
                    }
                } else {
                    this.$toast?.error(result.message || result.error || 'Failed to fetch UTSC data');
                }
            } catch (error) {
                console.error('Fetch UTSC data error:', error);
                if (!this.utscLiveMode) {
                    this.$toast?.error('Failed to fetch UTSC data');
                }
            } finally {
                this.runningUtsc = false;
            }
        },
        
        async toggleUtscLiveMode() {
            this.utscLiveMode = !this.utscLiveMode;
            
            if (this.utscLiveMode) {
                console.log('[UTSC] Starting live mode...');
                
                // Chart should already be initialized from first measurement
                // If not, initialize it now
                if (!this.utscSciChart) {
                    console.log('[UTSC] Chart not initialized yet, initializing...');
                    await this.ensureSciChartLoaded();
                    await this.$nextTick();
                    await new Promise(resolve => setTimeout(resolve, 150));
                    await this.initUtscSciChart();
                }
                
                // Verify chart is ready
                if (!this.utscSciChart || !this.utscSciChartSeries) {
                    console.error('[UTSC] SciChart failed to initialize, aborting live mode');
                    this.$toast?.error('Failed to initialize chart');
                    this.utscLiveMode = false;
                    return;
                }
                
                console.log('[UTSC] SciChart ready, starting WebSocket...');
                this.$toast?.success('Live monitoring started (auto-restarts every 50s)');
                this.startUtscWebSocket();
                
                // Auto-restart UTSC measurement every 50 seconds (E6000 max is 60s)
                this.utscAutoRestartInterval = setInterval(async () => {
                    if (this.utscLiveMode && !this.runningUtsc) {
                        console.log('[UTSC] Auto-restarting measurement for continuous monitoring...');
                        await this.startUtsc();
                    }
                }, 50000);  // Restart every 50 seconds
                
            } else {
                console.log('[UTSC] Stopping live mode...');
                this.$toast?.info('Live monitoring stopped');
                this.stopUtscWebSocket();
                
                // Clear auto-restart interval
                if (this.utscAutoRestartInterval) {
                    clearInterval(this.utscAutoRestartInterval);
                    this.utscAutoRestartInterval = null;
                }
            }
        },
        
        startUtscWebSocket() {
            if (!this.selectedModem) return;
            
            // Close existing connection
            this.stopUtscWebSocket();
            
            const mac = this.selectedModem.mac_address;
            const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            // Pass refresh rate (ms) and duration (s) as query params
            const refreshMs = this.utscRefreshRate;
            const durationS = this.utscDuration;
            const rfPort = this.utscConfig.rfPortIfindex;
            const cmtsIp = this.selectedModem.cmts_ip;
            const community = this.selectedModem.cmts_community || this.snmpCommunityRW || 'Z1gg0Sp3c1@l';
            const wsUrl = `${wsProtocol}//${window.location.host}/ws/utsc/${mac}?refresh=${refreshMs}&duration=${durationS}&rf_port=${rfPort}&cmts_ip=${cmtsIp}&community=${encodeURIComponent(community)}`;
            
            console.log('[UTSC] Connecting WebSocket:', wsUrl);
            
            try {
                this.utscWebSocket = new WebSocket(wsUrl);
                
                this.utscWebSocket.onopen = () => {
                    console.log('[UTSC] WebSocket connected');
                    this.$toast?.success(`UTSC stream: ${(refreshMs/1000).toFixed(1)}s refresh, ${durationS}s duration`);
                };
                
                this.utscWebSocket.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        
                        if (data.type === 'spectrum') {
                            // Update buffer size display
                            if (data.buffer_size !== undefined) {
                                this.utscBufferSize = data.buffer_size;
                            }
                            
                            // Throttle updates to prevent browser overload
                            const now = Date.now();
                            if (now - this.utscLastUpdateTime < this.utscUpdateThrottle) {
                                return; // Skip this update
                            }
                            this.utscLastUpdateTime = now;
                            
                            // Handle interactive mode with SciChart
                            if (this.utscInteractive && data.raw_data) {
                                this.$nextTick(() => {
                                    this.updateUtscSciChart(data.raw_data);
                                });
                            }
                            
                            // Always update plot for fallback/static mode
                            if (data.plot) {
                                this.utscPlotImage = {
                                    data: data.plot.data,
                                    filename: data.plot.filename,
                                    _timestamp: data.timestamp
                                };
                                
                                // Render Chart.js if not in interactive mode
                                if (!this.utscInteractive) {
                                    this.$nextTick(() => {
                                        this.renderUtscChart();
                                    });
                                }
                            }
                        } else if (data.type === 'buffering') {
                            // Show buffering progress
                            if (data.buffer_size !== undefined) {
                                this.utscBufferSize = data.buffer_size;
                            }
                            if (data.message) {
                                console.log('[UTSC]', data.message);
                            }
                        } else if (data.type === 'buffering_complete') {
                            // Buffering complete, stream starting
                            console.log('[UTSC]', data.message);
                            this.$toast?.success(data.message);
                        } else if (data.type === 'heartbeat') {
                            // Update buffer size from heartbeat
                            if (data.buffer_size !== undefined) {
                                this.utscBufferSize = data.buffer_size;
                            }
                        } else if (data.type === 'error') {
                            console.error('[UTSC] Stream error:', data.message);
                        } else if (data.type === 'connected') {
                            console.log('[UTSC]', data.message);
                        }
                    } catch (e) {
                        console.error('[UTSC] Failed to parse message:', e);
                    }
                };
                
                this.utscWebSocket.onerror = (error) => {
                    console.error('[UTSC] WebSocket error:', error);
                    this.$toast?.error('UTSC stream error');
                };
                
                this.utscWebSocket.onclose = () => {
                    console.log('[UTSC] WebSocket closed');
                    if (this.utscLiveMode) {
                        // Try to reconnect after 2 seconds
                        setTimeout(() => {
                            if (this.utscLiveMode) {
                                console.log('[UTSC] Attempting reconnect...');
                                this.startUtscWebSocket();
                            }
                        }, 2000);
                    }
                };
            } catch (e) {
                console.error('[UTSC] Failed to create WebSocket:', e);
                this.$toast?.error('Failed to connect UTSC stream');
            }
        },
        
        stopUtscWebSocket() {
            if (this.utscWebSocket) {
                this.utscWebSocket.close();
                this.utscWebSocket = null;
            }
            // Also stop any polling fallback
            if (this.utscLiveInterval) {
                clearInterval(this.utscLiveInterval);
                this.utscLiveInterval = null;
            }
            // Clean up SciChart
            this.destroyUtscSciChart();
        },
        
        async ensureSciChartLoaded() {
            // Wait for SciChart library to load (max 10 seconds)
            const maxWait = 10000;
            const interval = 100;
            let waited = 0;
            
            while (typeof SciChart === 'undefined' && waited < maxWait) {
                await new Promise(resolve => setTimeout(resolve, interval));
                waited += interval;
            }
            
            if (typeof SciChart === 'undefined') {
                console.error('SciChart failed to load after', maxWait, 'ms');
                this.$toast?.error('SciChart library failed to load');
                return false;
            }
            
            console.log('[SciChart] Library loaded successfully');
            return true;
        },
        
        async initUtscSciChart() {
            // Destroy existing chart first
            this.destroyUtscSciChart();
            
            try {
                // Ensure SciChart is loaded
                const loaded = await this.ensureSciChartLoaded();
                if (!loaded) {
                    console.warn('SciChart not loaded, cannot initialize chart');
                    return;
                }
                
                // Check if div exists
                const chartDiv = document.getElementById('utscSciChart');
                if (!chartDiv) {
                    console.error('[SciChart] Chart div not found in DOM');
                    return;
                }
                
                console.log('[SciChart] Initializing chart...');
                
                const { SciChartSurface, NumericAxis, FastLineRenderableSeries, XyDataSeries, EAxisAlignment, NumberRange, ZoomPanModifier, MouseWheelZoomModifier, ZoomExtentsModifier } = SciChart;
                
                // Use community license to avoid license server checks
                SciChartSurface.UseCommunityLicense();
                
                // Create the chart surface
                const { sciChartSurface, wasmContext } = await SciChartSurface.create('utscSciChart');
                
                // Add axes
                sciChartSurface.xAxes.add(new NumericAxis(wasmContext, { 
                    axisAlignment: EAxisAlignment.Bottom,
                    axisTitle: 'Frequency (MHz)',
                    labelPrecision: 0,
                    visibleRange: new NumberRange(0, 100)
                }));
                
                sciChartSurface.yAxes.add(new NumericAxis(wasmContext, { 
                    axisAlignment: EAxisAlignment.Left,
                    axisTitle: 'Power (dBmV)',
                    labelPrecision: 1,
                    autoRange: 'Always'
                }));
                
                // Create data series
                const dataSeries = new XyDataSeries(wasmContext);
                const series = new FastLineRenderableSeries(wasmContext, {
                    dataSeries,
                    strokeThickness: 2,
                    stroke: '#00aaff'
                });
                
                sciChartSurface.renderableSeries.add(series);
                
                // Add interactivity
                sciChartSurface.chartModifiers.add(new ZoomPanModifier());
                sciChartSurface.chartModifiers.add(new MouseWheelZoomModifier());
                sciChartSurface.chartModifiers.add(new ZoomExtentsModifier());
                
                // Store references
                this.utscSciChart = sciChartSurface;
                this.utscSciChartSeries = dataSeries;
                
                console.log('[SciChart] Initialized successfully');
            } catch (error) {
                console.error('[SciChart] Initialization failed:', error);
                this.$toast?.error('Failed to initialize interactive chart');
            }
        },
        
        updateUtscSciChart(rawData) {
            if (!this.utscSciChart || !this.utscSciChartSeries) {
                console.warn('[SciChart] Chart not initialized, skipping update');
                return;
            }
            
            try {
                const { frequencies, amplitudes } = rawData;
                
                if (!frequencies || !amplitudes || frequencies.length === 0) {
                    console.warn('[SciChart] No data to update');
                    return;
                }
                
                console.log('[SciChart] Updating with', frequencies.length, 'points');
                
                // Convert Hz to MHz for display
                const freqsMhz = frequencies.map(f => f / 1e6);
                
                // Create a new data series instead of clearing (avoids WebAssembly binding issues)
                const { XyDataSeries } = SciChart;
                const newDataSeries = new XyDataSeries(this.utscSciChart.webAssemblyContext2D);
                newDataSeries.appendRange(freqsMhz, amplitudes);
                
                // Replace the old data series in the renderable series
                const renderableSeries = this.utscSciChart.renderableSeries.get(0);
                renderableSeries.dataSeries = newDataSeries;
                
                // Update reference
                this.utscSciChartSeries = newDataSeries;
                
                console.log('[SciChart] Data updated successfully');
                
            } catch (error) {
                console.error('[SciChart] Update failed:', error);
            }
        },
        
        destroyUtscSciChart() {
            if (this.utscSciChart) {
                try {
                    this.utscSciChart.delete();
                } catch (e) {
                    console.error('[SciChart] Destroy error:', e);
                }
                this.utscSciChart = null;
                this.utscSciChartSeries = null;
            }
        },
        
        // Legacy polling methods (kept as fallback)
        startUtscLiveMonitoring() {
            if (this.utscLiveInterval) {
                clearInterval(this.utscLiveInterval);
            }
            
            // Fetch immediately
            this.fetchUtscData();
            
            // Then fetch at regular intervals
            this.utscLiveInterval = setInterval(() => {
                if (this.utscLiveMode && this.selectedModem && this.utscConfig.rfPortIfindex) {
                    this.fetchUtscData();
                } else {
                    this.stopUtscLiveMonitoring();
                }
            }, this.utscRefreshRate);
        },
        
        stopUtscLiveMonitoring() {
            if (this.utscLiveInterval) {
                clearInterval(this.utscLiveInterval);
                this.utscLiveInterval = null;
            }
        },
        
        restartUtscLiveMonitoring() {
            // Restart with new refresh rate if live mode is active
            if (this.utscLiveMode) {
                this.startUtscLiveMonitoring();
            }
        },
        
        async fetchUsRxmerData() {
            if (!this.selectedModem || !this.selectedModem.cmts_ip) {
                return;
            }
            
            try {
                const response = await fetch(`/api/pypnm/upstream/rxmer/data/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip,
                        ofdma_ifindex: this.usRxmerConfig.ofdmaIfindex,
                        community: this.selectedModem.cmts_community || 'Z1gg0@LL'
                    })
                });
                
                const result = await response.json();
                
                if (result.success && result.data) {
                    this.usRxmerSpectrumData = result.data;
                    this.$toast?.success('US RxMER data loaded');
                    this.$nextTick(() => this.renderUsRxmerChart());
                } else {
                    this.$toast?.error(result.error || 'Failed to fetch US RxMER data');
                }
            } catch (error) {
                console.error('Fetch US RxMER data error:', error);
                this.$toast?.error('Failed to fetch US RxMER data');
            }
        },
        
        renderUtscChart() {
            console.log('[UTSC] renderUtscChart called, hasPlotImage:', !!this.utscPlotImage, 'timestamp:', this.utscPlotImage?._timestamp);
            const container = document.getElementById('utscChartContainer');
            if (!container) return;
            
            // If we have a matplotlib plot, display it as an image
            if (this.utscPlotImage && this.utscPlotImage.data) {
                // Convert base64 to Blob URL to bypass browser caching
                try {
                    const binary = atob(this.utscPlotImage.data);
                    const array = new Uint8Array(binary.length);
                    for (let i = 0; i < binary.length; i++) {
                        array[i] = binary.charCodeAt(i);
                    }
                    const blob = new Blob([array], { type: 'image/png' });
                    const blobUrl = URL.createObjectURL(blob);
                    
                    // Revoke old blob URL
                    if (this._currentBlobUrl) {
                        URL.revokeObjectURL(this._currentBlobUrl);
                    }
                    this._currentBlobUrl = blobUrl;
                    
                    // Check if we already have an image element
                    let img = container.querySelector('img');
                    if (img) {
                        // Just update the src - browser handles smooth update
                        img.src = blobUrl;
                    } else {
                        // First time - create the image
                        container.innerHTML = `
                            <img src="${blobUrl}" 
                                 alt="UTSC Spectrum" 
                                 style="width: 100%; height: auto; max-height: 600px; object-fit: contain;" />
                        `;
                    }
                } catch (e) {
                    console.error('[UTSC] Failed to create Blob URL:', e);
                }
                return;
            }
            
            // Fallback to Chart.js if no matplotlib plot available
            const canvas = document.getElementById('utscChart');
            if (!canvas || !this.utscSpectrumData) return;
            
            // Destroy existing chart
            if (this.utscChartInstance) {
                this.utscChartInstance.destroy();
            }
            
            const data = this.utscSpectrumData;
            
            // Convert frequencies from Hz to MHz for display
            const freqsMhz = (data.frequencies || []).map(f => f / 1e6);
            
            const ctx = canvas.getContext('2d');
            
            this.utscChartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: freqsMhz,
                    datasets: [{
                        label: 'Power (dBmV)',
                        data: data.amplitudes || [],
                        borderColor: 'rgb(75, 192, 192)',
                        backgroundColor: 'rgba(75, 192, 192, 0.1)',
                        borderWidth: 1,
                        fill: true,
                        pointRadius: 0,
                        tension: 0.1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: {
                            title: {
                                display: true,
                                text: 'Frequency (MHz)'
                            },
                            ticks: {
                                maxTicksLimit: 20
                            }
                        },
                        y: {
                            title: {
                                display: true,
                                text: 'Power (dBmV)'
                            }
                        }
                    },
                    plugins: {
                        legend: {
                            display: true
                        },
                        title: {
                            display: true,
                            text: `Upstream Spectrum - ${data.filename || 'N/A'}`
                        }
                    }
                }
            });
        },
        
        renderUsRxmerChart() {
            const canvas = document.getElementById('usRxmerChart');
            if (!canvas || !this.usRxmerSpectrumData) return;
            
            if (this.usRxmerChartInstance) {
                this.usRxmerChartInstance.destroy();
            }
            
            const data = this.usRxmerSpectrumData;
            const ctx = canvas.getContext('2d');
            
            this.usRxmerChartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: data.subcarriers || [],
                    datasets: [{
                        label: 'RxMER (dB)',
                        data: data.rxmer_values || [],
                        borderColor: 'rgb(54, 162, 235)',
                        backgroundColor: 'rgba(54, 162, 235, 0.1)',
                        borderWidth: 1,
                        fill: true,
                        pointRadius: 0,
                        tension: 0.1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: {
                            title: {
                                display: true,
                                text: 'Subcarrier Index'
                            },
                            ticks: {
                                maxTicksLimit: 20
                            }
                        },
                        y: {
                            title: {
                                display: true,
                                text: 'RxMER (dB)'
                            },
                            min: 20,
                            max: 50
                        }
                    },
                    plugins: {
                        legend: {
                            display: true
                        },
                        title: {
                            display: true,
                            text: `Upstream OFDMA RxMER - OFDMA ifIndex ${data.ofdma_ifindex || 'N/A'}`
                        }
                    }
                }
            });
        },
        
        closeUtscSpectrum() {
            this.utscSpectrumData = null;
            this.utscPlotImage = null;
            if (this.utscChartInstance) {
                this.utscChartInstance.destroy();
                this.utscChartInstance = null;
            }
        },
        
        closeUsRxmerSpectrum() {
            this.usRxmerSpectrumData = null;
            if (this.usRxmerChartInstance) {
                this.usRxmerChartInstance.destroy();
                this.usRxmerChartInstance = null;
            }
        },

        async runPnmMeasurement(measurementType) {
            if (!this.selectedModem) return;
            
            this.runningTest = true;
            this.showRawData = false;
            
            try {
                const payload = {
                    modem_ip: this.selectedModem.ip_address,
                    community: this.snmpCommunityModem || 'z1gg0m0n1t0r1ng',
                    output_type: this.pnmOutputType
                };
                
                // Add measurement-specific parameters
                if (measurementType === 'fec_summary') {
                    payload.fec_summary_type = 2;  // 10-minute interval
                }
                if (measurementType === 'histogram') {
                    payload.sample_duration = 60;
                }
                
                const response = await fetch(`${API_BASE}/pypnm/measurements/${measurementType}/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                
                const data = await response.json();
                
                console.log('=== PNM Measurement Response ===');
                console.log('Status:', data.status);
                console.log('Has data field:', !!data.data);
                console.log('data.data:', data.data);
                console.log('Measurement type:', measurementType);
                console.log('Output type:', this.pnmOutputType);
                console.log('Plots:', data.plots);
                console.log('Plots count:', data.plots ? data.plots.length : 0);
                console.log('================================');
                
                if (data.status === 0) {
                    // Store data in the appropriate variable
                    this.selectedMeasurementData = data;
                    
                    // Map to legacy variables for compatibility
                    if (measurementType === 'rxmer') {
                        this.rxmerData = data;
                        this.$nextTick(() => {
                            this.drawRxmerCharts();
                        });
                    } else if (measurementType === 'spectrum') {
                        this.spectrumData = data;
                    } else if (measurementType === 'fec_summary') {
                        this.fecData = data;
                    } else if (measurementType === 'us_pre_eq') {
                        this.preEqData = data;
                    }
                    
                    // Draw charts if we have JSON data (data.data exists) or for measurements that always have charts
                    // For spectrum, we rely on matplotlib plots from the backend (in data.plots)
                    const hasJsonData = data.data || measurementType === 'rxmer' || measurementType === 'us_pre_eq';
                    const hasMatplotlibPlots = data.plots && data.plots.length > 0;
                    
                    if (hasJsonData && !hasMatplotlibPlots) {
                        console.log('Will call drawMeasurementCharts with:', measurementType, data);
                        this.$nextTick(() => {
                            this.drawMeasurementCharts(measurementType, data);
                        });
                    } else if (hasMatplotlibPlots) {
                        console.log(`Using ${data.plots.length} matplotlib plot(s) for ${measurementType}`);
                    } else {
                        console.log('Skipping chart draw - no JSON data available. Output type:', this.pnmOutputType);
                    }
                    
                    const typeNames = {
                        'rxmer': 'RxMER',
                        'spectrum': 'Spectrum Analyzer',
                        'channel_estimation': 'Channel Estimation',
                        'modulation_profile': 'Modulation Profile',
                        'fec_summary': 'FEC Summary',
                        'histogram': 'Histogram',
                        'constellation': 'Constellation Display',
                        'us_pre_eq': 'Upstream Pre-Equalization'
                    };
                    
                    this.showSuccess(
                        `${typeNames[measurementType] || measurementType} Complete`,
                        this.pnmOutputType === 'archive' 
                            ? 'Plots and CSV data generated successfully'
                            : 'Measurement data retrieved successfully'
                    );
                } else {
                    this.showError('Measurement Failed', data.message || `Error code: ${data.status}`);
                }
            } catch (error) {
                console.error('PNM measurement failed:', error);
                this.showError('Measurement Failed', error.message);
            } finally {
                this.runningTest = false;
            }
        },
        
        toggleRawData() {
            this.showRawData = !this.showRawData;
        },
        
        async loadChannelStats() {
            if (!this.selectedModem) return;
            
            try {
                const response = await fetch(`${API_BASE}/pypnm/channel-stats/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        modem_ip: this.selectedModem.ip_address,
                        community: this.snmpCommunityModem || 'z1gg0m0n1t0r1ng'
                    })
                });
                
                if (!response.ok) {
                    console.warn('Channel stats endpoint not available');
                    return;
                }
                
                const data = await response.json();
                
                if (data.status === 0) {
                    this.channelStats = data;
                }
            } catch (error) {
                console.warn('Failed to load channel stats:', error);
                // Don't show error to user, just skip channel stats
            }
        },
        
        async runHousekeeping() {
            try {
                const response = await fetch(`${API_BASE}/pypnm/housekeeping`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        max_age_days: this.housekeepingDays,
                        dry_run: this.housekeepingDryRun
                    })
                });
                
                const data = await response.json();
                this.housekeepingResult = data;
                
                if (data.status === 'success') {
                    this.showSuccess(
                        'Housekeeping Complete',
                        `${this.housekeepingDryRun ? 'Would delete' : 'Deleted'} ${data.deleted_count} files (${data.total_size_mb} MB)`
                    );
                } else {
                    this.showError('Housekeeping Failed', data.message);
                }
            } catch (error) {
                console.error('Housekeeping failed:', error);
                this.showError('Housekeeping Failed', error.message);
            }
        },
        
        async loadEventLog() {
            if (!this.selectedModem) return;
            
            this.runningTest = true;
            
            try {
                // Use PyPNM API for event log
                const response = await fetch(`${API_BASE}/pypnm/modem/${this.selectedModem.mac_address}/event-log`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        modem_ip: this.selectedModem.ip_address,
                        community: this.snmpCommunityModem || 'z1gg0m0n1t0r1ng'
                    })
                });
                
                const data = await response.json();
                
                // PyPNM returns { status: 0, logs: [...] } - status 0 = success
                if (data.status === 0 && data.logs && Array.isArray(data.logs)) {
                    // Transform PyPNM event format to our format
                    this.eventLog = data.logs.map((evt, idx) => ({
                        event_id: idx + 1,
                        timestamp: evt.docsDevEvLastTime || evt.docsDevEvFirstTime,
                        level: this.getEventLevelName(evt.docsDevEvLevel),
                        message: evt.docsDevEvText,
                        count: evt.docsDevEvCounts
                    }));
                    this.showSuccess('Event Log Loaded', `${this.eventLog.length} events retrieved.`);
                } else if (data.status !== 0) {
                    this.showError('Failed to load event log', data.message || `Error code: ${data.status}`);
                } else {
                    this.eventLog = [];
                    this.showError('No events', 'No event log entries found');
                }
            } catch (error) {
                console.error('Failed to load event log:', error);
                this.showError('Failed to load event log', error.message);
            } finally {
                this.runningTest = false;
            }
        },
        
        getEventLevelName(level) {
            // DOCSIS event levels: 1=emergency, 2=alert, 3=critical, 4=error, 5=warning, 6=notice, 7=info, 8=debug
            const levels = {
                1: 'EMERGENCY',
                2: 'ALERT', 
                3: 'CRITICAL',
                4: 'ERROR',
                5: 'WARNING',
                6: 'NOTICE',
                7: 'INFO',
                8: 'DEBUG'
            };
            return levels[level] || `LEVEL-${level}`;
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
        
        drawMeasurementCharts(type, data) {
            const container = document.getElementById('measurement-charts-container');
            if (!container) {
                console.warn('Chart container not found');
                return;
            }
            
            // Clear old charts
            container.innerHTML = '';
            
            console.log('Drawing charts for type:', type, 'with data:', data);
            
            // SKIP Chart.js for spectrum - we use matplotlib PNG plots instead
            if (type === 'spectrum') {
                console.log('Spectrum uses matplotlib plots - skipping Chart.js');
                return;
            }
            
            if (type === 'rxmer') {
                this.drawRxmerCharts();
            } else if (type === 'channel_estimation' && data.data) {
                this.drawChannelEstimationCharts(data.data);
            } else if (type === 'modulation_profile' && data.data) {
                this.drawModulationProfileCharts(data.data);
            } else if (type === 'fec_summary' && data.data) {
                this.drawFecSummaryCharts(data.data);
            } else if (type === 'histogram' && data.data) {
                this.drawHistogramCharts(data.data);
            } else if (type === 'constellation' && data.data) {
                this.drawConstellationCharts(data.data);
            } else if (type === 'us_pre_eq') {
                this.drawPreEqCharts();
            } else {
                container.innerHTML = '<div class="alert alert-info"><i class="bi bi-info-circle me-2"></i>No visualization available for this measurement type. Click "Raw Data" to see the results.</div>';
            }
        },
        
        drawSpectrumCharts(data) {
            const container = document.getElementById('measurement-charts-container');
            
            console.log('=== drawSpectrumCharts Debug ===');
            console.log('data:', data);
            console.log('data.analysis:', data.analysis);
            
            // Extract spectrum analysis data
            const analysis = data.analysis && data.analysis.length > 0 ? data.analysis[0] : null;
            console.log('analysis:', analysis);
            
            if (!analysis || !analysis.signal_analysis) {
                console.error('No spectrum analysis data found');
                container.innerHTML = '<div class="alert alert-warning"><i class="bi bi-exclamation-triangle me-2"></i>No spectrum analysis data available.</div>';
                return;
            }
            
            const signalAnalysis = analysis.signal_analysis;
            const frequencies = signalAnalysis.frequencies || [];
            const magnitudes = signalAnalysis.magnitudes || [];
            
            if (frequencies.length === 0 || magnitudes.length === 0) {
                container.innerHTML = '<div class="alert alert-warning"><i class="bi bi-exclamation-triangle me-2"></i>Empty spectrum data.</div>';
                return;
            }
            
            // Convert frequencies from Hz to MHz for display
            const freqsMHz = frequencies.map(f => f / 1000000);
            
            // Downsample if too many points (for performance)
            const maxPoints = 5000;
            let displayFreqs = freqsMHz;
            let displayMags = magnitudes;
            
            if (frequencies.length > maxPoints) {
                const step = Math.ceil(frequencies.length / maxPoints);
                displayFreqs = freqsMHz.filter((_, i) => i % step === 0);
                displayMags = magnitudes.filter((_, i) => i % step === 0);
            }
            
            // Create chart container
            const chartDiv = document.createElement('div');
            chartDiv.className = 'mb-4';
            chartDiv.innerHTML = `
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <h6 class="mb-0">Full Spectrum Analysis (${analysis.capture_parameters.first_segment_center_freq / 1e6} - ${analysis.capture_parameters.last_segment_center_freq / 1e6} MHz)</h6>
                    <small class="text-muted">${displayFreqs.length} points displayed (${frequencies.length} total)</small>
                </div>
                <canvas id="spectrum-chart" height="300"></canvas>
            `;
            container.appendChild(chartDiv);
            
            const canvas = chartDiv.querySelector('canvas');
            
            new Chart(canvas.getContext('2d'), {
                type: 'line',
                data: {
                    labels: displayFreqs,
                    datasets: [{
                        label: 'Magnitude (dBmV)',
                        data: displayMags,
                        borderColor: 'rgb(54, 162, 235)',
                        backgroundColor: 'rgba(54, 162, 235, 0.1)',
                        borderWidth: 1,
                        pointRadius: 0,
                        tension: 0
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {
                        mode: 'nearest',
                        axis: 'x',
                        intersect: false
                    },
                    plugins: {
                        title: {
                            display: true,
                            text: 'Spectrum Analyzer - Full Frequency Sweep'
                        },
                        legend: {
                            display: true
                        },
                        tooltip: {
                            callbacks: {
                                title: function(context) {
                                    return `${context[0].label} MHz`;
                                },
                                label: function(context) {
                                    return `Power: ${context.parsed.y.toFixed(2)} dBmV`;
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            type: 'linear',
                            title: {
                                display: true,
                                text: 'Frequency (MHz)'
                            },
                            ticks: {
                                callback: function(value) {
                                    return value.toFixed(0);
                                }
                            }
                        },
                        y: {
                            title: {
                                display: true,
                                text: 'Magnitude (dBmV)'
                            }
                        }
                    }
                }
            });
            
            // Add device info if available
            if (analysis.device_details && analysis.device_details.system_description) {
                const deviceInfo = analysis.device_details.system_description;
                const infoDiv = document.createElement('div');
                infoDiv.className = 'alert alert-info mt-3';
                infoDiv.innerHTML = `
                    <h6><i class="bi bi-info-circle me-2"></i>Device Information</h6>
                    <div class="row">
                        <div class="col-md-3"><strong>Vendor:</strong> ${deviceInfo.VENDOR || 'N/A'}</div>
                        <div class="col-md-3"><strong>Model:</strong> ${deviceInfo.MODEL || 'N/A'}</div>
                        <div class="col-md-3"><strong>SW Version:</strong> ${deviceInfo.SW_REV || 'N/A'}</div>
                        <div class="col-md-3"><strong>HW Version:</strong> ${deviceInfo.HW_REV || 'N/A'}</div>
                    </div>
                `;
                container.appendChild(infoDiv);
            }
        },
        
        drawChannelEstimationCharts(data) {
            const container = document.getElementById('measurement-charts-container');
            const measurements = data.rxmer_measurements || data.channel_measurements || [];
            
            measurements.forEach(meas => {
                const chartDiv = document.createElement('div');
                chartDiv.className = 'mb-4';
                chartDiv.innerHTML = `
                    <h6>Channel ${meas.channel_id || meas.if_index}</h6>
                    <canvas id="chanest-${meas.channel_id || meas.if_index}" height="250"></canvas>
                `;
                container.appendChild(chartDiv);
                
                const canvas = chartDiv.querySelector('canvas');
                const coeffs = meas.coefficients || meas.channel_estimation || [];
                
                new Chart(canvas.getContext('2d'), {
                    type: 'line',
                    data: {
                        labels: coeffs.map((_, i) => i),
                        datasets: [{
                            label: 'Magnitude',
                            data: coeffs.map(c => c.magnitude || c),
                            borderColor: 'rgb(75, 192, 192)',
                            tension: 0.1
                        }]
                    },
                    options: {
                        responsive: true,
                        plugins: { title: { display: true, text: 'Channel Estimation Coefficients' } }
                    }
                });
            });
        },
        
        drawModulationProfileCharts(data) {
            const container = document.getElementById('measurement-charts-container');
            const profiles = data.modulation_profiles || [];
            
            profiles.forEach(prof => {
                const chartDiv = document.createElement('div');
                chartDiv.className = 'mb-4';
                chartDiv.innerHTML = `
                    <h6>Profile ${prof.profile_id}</h6>
                    <canvas id="modprof-${prof.profile_id}" height="250"></canvas>
                `;
                container.appendChild(chartDiv);
                
                const canvas = chartDiv.querySelector('canvas');
                const subcarriers = prof.subcarriers || [];
                
                new Chart(canvas.getContext('2d'), {
                    type: 'bar',
                    data: {
                        labels: subcarriers.map(s => s.index),
                        datasets: [{
                            label: 'Modulation Order',
                            data: subcarriers.map(s => s.modulation_order || s.modulation),
                            backgroundColor: 'rgba(54, 162, 235, 0.5)'
                        }]
                    },
                    options: {
                        responsive: true,
                        plugins: { title: { display: true, text: 'Modulation Profile' } }
                    }
                });
            });
        },
        
        drawFecSummaryCharts(data) {
            const container = document.getElementById('measurement-charts-container');
            const summaries = data.fec_summaries || [];
            
            summaries.forEach(fec => {
                const chartDiv = document.createElement('div');
                chartDiv.className = 'mb-4';
                chartDiv.innerHTML = `
                    <h6>Channel ${fec.channel_id} - Profile ${fec.profile_id}</h6>
                    <canvas id="fec-${fec.channel_id}-${fec.profile_id}" height="250"></canvas>
                `;
                container.appendChild(chartDiv);
                
                const canvas = chartDiv.querySelector('canvas');
                
                new Chart(canvas.getContext('2d'), {
                    type: 'bar',
                    data: {
                        labels: ['Total', 'Corrected', 'Uncorrectable'],
                        datasets: [{
                            label: 'Codewords',
                            data: [
                                fec.total_codewords || 0,
                                fec.corrected_codewords || 0,
                                fec.uncorrectable_codewords || 0
                            ],
                            backgroundColor: [
                                'rgba(54, 162, 235, 0.5)',
                                'rgba(75, 192, 192, 0.5)',
                                'rgba(255, 99, 132, 0.5)'
                            ]
                        }]
                    },
                    options: {
                        responsive: true,
                        plugins: { title: { display: true, text: 'FEC Statistics' } }
                    }
                });
            });
        },
        
        drawHistogramCharts(data) {
            const container = document.getElementById('measurement-charts-container');
            const histograms = data.histograms || [];
            
            histograms.forEach(hist => {
                const chartDiv = document.createElement('div');
                chartDiv.className = 'mb-4';
                chartDiv.innerHTML = `
                    <h6>Channel ${hist.channel_id}</h6>
                    <canvas id="hist-${hist.channel_id}" height="250"></canvas>
                `;
                container.appendChild(chartDiv);
                
                const canvas = chartDiv.querySelector('canvas');
                const bins = hist.bins || hist.histogram_data || [];
                
                new Chart(canvas.getContext('2d'), {
                    type: 'bar',
                    data: {
                        labels: bins.map(b => b.power_level || b.bin),
                        datasets: [{
                            label: 'Count',
                            data: bins.map(b => b.count || b.value),
                            backgroundColor: 'rgba(153, 102, 255, 0.5)'
                        }]
                    },
                    options: {
                        responsive: true,
                        plugins: { title: { display: true, text: 'Power Histogram' } },
                        scales: {
                            x: { title: { display: true, text: 'Power Level (dBmV)' } },
                            y: { title: { display: true, text: 'Count' } }
                        }
                    }
                });
            });
        },
        
        drawConstellationCharts(data) {
            const container = document.getElementById('measurement-charts-container');
            const constellations = data.constellations || [];
            
            constellations.forEach(constellation => {
                const chartDiv = document.createElement('div');
                chartDiv.className = 'mb-4';
                chartDiv.innerHTML = `
                    <h6>Channel ${constellation.channel_id}</h6>
                    <canvas id="constellation-${constellation.channel_id}" height="400"></canvas>
                `;
                container.appendChild(chartDiv);
                
                const canvas = chartDiv.querySelector('canvas');
                const points = constellation.points || [];
                
                new Chart(canvas.getContext('2d'), {
                    type: 'scatter',
                    data: {
                        datasets: [{
                            label: 'IQ Points',
                            data: points.map(p => ({ x: p.i || p.real, y: p.q || p.imag })),
                            backgroundColor: 'rgba(255, 159, 64, 0.5)',
                            pointRadius: 2
                        }]
                    },
                    options: {
                        responsive: true,
                        plugins: { title: { display: true, text: 'Constellation Display' } },
                        scales: {
                            x: { title: { display: true, text: 'I (In-Phase)' } },
                            y: { title: { display: true, text: 'Q (Quadrature)' } }
                        }
                    }
                });
            });
        },
        
        drawRxmerCharts() {
            if (!this.rxmerData || !this.rxmerData.data || !this.rxmerData.data.rxmer_measurements) {
                console.warn('RxMER data not available for charting');
                return;
            }
            
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
        
        drawDsChannelChart() {
            if (!this.systemInfo || !this.systemInfo.downstream) return;
            
            const canvas = document.getElementById('ds-channel-chart');
            if (!canvas) return;
            
            // Destroy existing chart
            if (this.charts['ds-channel-chart']) {
                this.charts['ds-channel-chart'].destroy();
            }
            
            const channels = this.systemInfo.downstream.filter(c => c.frequency_mhz > 0).sort((a, b) => a.frequency_mhz - b.frequency_mhz);
            const labels = channels.map(c => c.frequency_mhz.toFixed(0));
            const powerData = channels.map(c => c.power_dbmv);
            const snrData = channels.map(c => c.snr_db);
            
            this.charts['ds-channel-chart'] = new Chart(canvas.getContext('2d'), {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [
                        {
                            label: 'Power (dBmV)',
                            data: powerData,
                            backgroundColor: 'rgba(13, 110, 253, 0.7)',
                            borderColor: 'rgb(13, 110, 253)',
                            borderWidth: 1,
                            yAxisID: 'y'
                        },
                        {
                            label: 'MER (dB)',
                            data: snrData,
                            backgroundColor: 'rgba(25, 135, 84, 0.7)',
                            borderColor: 'rgb(25, 135, 84)',
                            borderWidth: 1,
                            yAxisID: 'y1'
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { position: 'top' } },
                    scales: {
                        x: { title: { display: true, text: 'Frequency (MHz)' } },
                        y: { type: 'linear', position: 'left', title: { display: true, text: 'Power (dBmV)' }, min: -10, max: 20 },
                        y1: { type: 'linear', position: 'right', title: { display: true, text: 'MER (dB)' }, min: 30, max: 50, grid: { drawOnChartArea: false } }
                    }
                }
            });
        },
        
        drawUsChannelChart() {
            if (!this.systemInfo || !this.systemInfo.upstream) return;
            
            const canvas = document.getElementById('us-channel-chart');
            if (!canvas) return;
            
            if (this.charts['us-channel-chart']) {
                this.charts['us-channel-chart'].destroy();
            }
            
            const channels = this.systemInfo.upstream;
            const labels = channels.map(c => `Ch ${c.channel_id}`);
            const powerData = channels.map(c => c.power_dbmv);
            const bgColors = powerData.map(p => p >= 35 && p <= 52 ? 'rgba(25, 135, 84, 0.7)' : 'rgba(220, 53, 69, 0.7)');
            
            this.charts['us-channel-chart'] = new Chart(canvas.getContext('2d'), {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'TX Power (dBmV)',
                        data: powerData,
                        backgroundColor: bgColors,
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { title: { display: true, text: 'Power (dBmV)' }, min: 30, max: 55 }
                    }
                }
            });
        },
        
        drawPreEqCharts() {
            if (!this.preEqData || !this.preEqData.results) return;
            
            Object.entries(this.preEqData.results).forEach(([chId, chData]) => {
                const canvasId = `preeq-chart-${chId}`;
                const canvas = document.getElementById(canvasId);
                if (!canvas) return;
                
                if (this.charts[canvasId]) {
                    this.charts[canvasId].destroy();
                }
                
                const coeffs = chData.forward_coefficients || [];
                const labels = coeffs.map((_, i) => i);
                const magnitudes = coeffs.map(c => c.magnitude_power_dB);
                
                this.charts[canvasId] = new Chart(canvas.getContext('2d'), {
                    type: 'bar',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'Tap Magnitude (dB)',
                            data: magnitudes,
                            backgroundColor: 'rgba(111, 66, 193, 0.7)',
                            borderColor: 'rgb(111, 66, 193)',
                            borderWidth: 1
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { display: false } },
                        scales: {
                            x: { title: { display: true, text: 'Tap Index' } },
                            y: { title: { display: true, text: 'Magnitude (dB)' } }
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
        
        // ============== Power Level Classes ==============
        
        getDsPowerClass(power) {
            // Downstream power: ideal range is -7 to +7 dBmV
            // Warning: -10 to -7 or +7 to +10
            // Danger: below -10 or above +10
            if (power === null || power === undefined) return 'text-muted';
            if (power < -10 || power > 10) return 'text-danger fw-bold';
            if (power < -7 || power > 7) return 'text-warning';
            return 'text-success';
        },
        
        getUsPowerClass(power) {
            // Upstream TX power: ideal range is 35 to 49 dBmV
            // Warning: 49-51 or 33-35
            // Danger: above 51 or below 33
            if (power === null || power === undefined) return 'text-muted';
            if (power > 51 || power < 33) return 'text-danger fw-bold';
            if (power > 49 || power < 35) return 'text-warning';
            return 'text-success';
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
