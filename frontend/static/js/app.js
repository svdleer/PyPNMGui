// PyPNM Web GUI - Main Application

const { createApp } = Vue;

// Get base path from window object (set by backend template)
const BASE_PATH = window.BASE_PATH || '';
const API_BASE = BASE_PATH + '/api';

createApp({
    data() {
        return {
            // Navigation
            currentView: 'home',
            
            // API Status
            apiStatus: 'mock',
            pypnmHealthy: false,
            agentCount: 0,
            
            // Loading state
            isLoading: false,
            loadingSystemInfo: false,
            runningTest: false,
            
            // Search parameters
            searchType: 'ip',
            searchValue: '',
            snmpCommunity: 'public',
            snmpCommunityRW: 'private',
            snmpCommunityModem: 'private',
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
                ofdmaChannels: []    // OFDMA upstream channels [{ifindex, index}]
            },
            utscConfig: {
                triggerMode: 2,  // 2=FreeRunning, 5=IdleSID, 6=CM_MAC
                centerFreqMhz: 45,
                spanMhz: 80,
                numBins: 800,
                rfPortIfindex: null,
                repeatPeriodMs: 50,       // 50ms between captures (20 fps)
                freerunDurationMs: 600000, // 10 min max (E6000 ignores this for file count)
                outputFormat: 0,          // 0=auto-detect (tries 5 then 2), 5=fftAmplitude (best for visualisation)
                window: 4,                // 4=blackmanHarris
                runtime: 60               // seconds - streaming runtime for spectrum analyzer
            },
            usRxmerConfig: {
                ofdmaIfindex: null,
                preEq: true,
                numCaptures: 5
            },
            runningUtsc: false,
            runningUsRxmer: false,
            utscStatus: null,
            usRxmerStatus: null,
            utscSpectrumData: null,
            usRxmerSpectrumData: null,
            spectrumAnalyzerModalOpen: false,
            usRxmerChartInstance: null,
            // Multi-capture RxMER
            usRxmerCaptures: [],          // [{index, image_data, timestamp, status}]
            usRxmerCaptureIndex: 0,       // current capture number
            usRxmerCaptureTotal: 0,       // total captures requested
            usRxmerDisplayIndex: 0,       // which capture is displayed
            usRxmerPreloadedImage: null,  // preloaded next image
            
            // Live Spectrum Analyzer with Buffering
            liveSpectrumEnabled: false,
            liveSpectrumPolling: false,
            liveSpectrumBuffer: [],      // Array of {timestamp, amplitudes, frequencies}
            liveSpectrumBufferSize: 50,  // Max captures to keep
            liveSpectrumIntervalMs: 1000, // Poll interval in ms
            liveSpectrumIntervalId: null,
            liveSpectrumStats: {
                captures: 0,
                lastUpdate: null,
                avgRefreshMs: 0
            },
            
            // Housekeeping
            housekeepingDays: 7,
            housekeepingDryRun: true,
            housekeepingResult: null,
            
            // Live modem loading
            loadingLiveModems: false,
            liveModemSource: '',
            enrichModems: true,
            enrichmentProgress: { current: 0, total: 0 },
            
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
        },
        
        // Check if modem has downstream OFDM channels (DOCSIS 3.1)
        hasOfdmChannels() {
            return this.channelStats?.downstream?.ofdm?.count > 0 ||
                   this.selectedModem?.docsis_version?.includes('3.1');
        },
        
        // Check if modem has upstream OFDMA channels (DOCSIS 3.1)
        hasOfdmaChannels() {
            return this.channelStats?.upstream?.ofdma?.count > 0 || 
                   this.upstreamInterfaces?.ofdmaChannels?.length > 0 ||
                   this.selectedModem?.upstream_interface?.toLowerCase()?.includes('ofdma');
        },
        
        // OFDM status: 'green' (operational), 'orange' (partial service), 'red' (offline/no channels)
        ofdmStatus() {
            if (!this.channelStats || this.selectedModem?.status === 'offline' || this.selectedModem?.status === 'other') {
                return 'red';
            }
            const ofdmChannels = this.channelStats?.downstream?.ofdm?.channels || [];
            if (ofdmChannels.length === 0) {
                return 'red';
            }
            // Check if any channel has partial service
            const hasPartialService = ofdmChannels.some(ch => ch.is_partial === true || ch.ncp_profile === true);
            return hasPartialService ? 'orange' : 'green';
        },
        
        // OFDMA status: 'green' (operational), 'red' (offline/no channels)
        // Only show green if channel stats actually loaded with OFDMA channels
        ofdmaStatus() {
            if (!this.channelStats || this.selectedModem?.status === 'offline' || this.selectedModem?.status === 'other') {
                return 'red';
            }
            const ofdmaChannels = this.channelStats?.upstream?.ofdma?.channels || [];
            return ofdmaChannels.length > 0 ? 'green' : 'red';
        },
        
        // Measurements requiring downstream OFDM
        requiresOfdm() {
            const ofdmRequired = ['rxmer', 'channel_estimation', 'modulation_profile', 'fec_summary', 'histogram', 'constellation'];
            return ofdmRequired.includes(this.pnmMeasurementType);
        },
        
        // Check if selected measurement can run
        canRunMeasurement() {
            if (!this.selectedModem) return false;
            if (this.runningTest) return false;
            // spectrum and us_pre_eq work without OFDM
            if (this.pnmMeasurementType === 'spectrum') return true;
            if (this.pnmMeasurementType === 'us_pre_eq') return this.hasOfdmaChannels;
            // Other measurements require OFDM
            return this.hasOfdmChannels;
        }
    },
    
    async mounted() {
        // Check API health
        await this.checkApiHealth();
        
        // Load community strings from server config
        await this.loadConfig();
        
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
        
        async loadConfig() {
            try {
                const response = await fetch(`${API_BASE}/pypnm/config`);
                const data = await response.json();
                if (data.snmpCommunity) this.snmpCommunity = data.snmpCommunity;
                if (data.snmpCommunityRW) this.snmpCommunityRW = data.snmpCommunityRW;
                if (data.snmpCommunityModem) this.snmpCommunityModem = data.snmpCommunityModem;
            } catch (e) {
                console.warn('Could not load server config, using defaults', e);
            }
        },
        
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
                    // Get agent count
                    try {
                        const agentResp = await fetch(`${API_BASE}/agent/status`);
                        const agentData = await agentResp.json();
                        this.agentCount = agentData.agents?.filter(a => a.status === 'connected').length || 0;
                    } catch (e) {
                        this.agentCount = 0;
                    }
                } catch (e) {
                    this.pypnmHealthy = false;
                    this.agentCount = 0;
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
            this.enrichmentProgress = { current: 0, total: 0 };
            
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
                        cmts_interface: m.interface || m.cmts_index || 'N/A',
                        software_version: m.software_version || '',
                        cable_mac: m.cable_mac || '',
                        upstream_interface: m.upstream_interface || '',
                        fiber_node: m.fiber_node || '',
                        partial_service: Boolean(m.partial_service) && m.partial_service !== 'false' && m.partial_service !== '0'
                    }));
                    
                    // Set enrichment progress if available
                    if (data.enrichment_progress) {
                        this.enrichmentProgress = {
                            current: data.enrichment_progress.completed || 0,
                            total: data.enrichment_progress.total || data.count
                        };
                    }
                    
                    const cacheInfo = data.cached ? ' (cached)' : '';
                    const enrichInfo = data.enriched ? ' [enriched]' : (data.enriching ? ' [enriching in background...]' : '');
                    this.liveModemSource = `Live data from ${data.cmts_hostname} (${data.cmts_ip}) via agent ${data.agent_id} - ${data.count} modems${cacheInfo}${enrichInfo}`;
                    this.searchPerformed = true;
                    
                    // Auto-refresh after 15s to get enriched data
                    if (this.enrichModems && !data.enriched && !data.cached) {
                        console.log('Scheduling auto-refresh in 15s for enriched data...');
                        setTimeout(() => this.refreshEnrichedModems(), 15000);
                    }
                } else {
                    this.showError('Failed to get modems', data.message || 'Unknown error');
                }
            } catch (error) {
                console.error('Failed to get live modems:', error);
                this.showError('Failed to get modems', error.message);
            } finally {
                this.loadingLiveModems = false;
                this.enrichmentProgress = { current: 0, total: 0 };
            }
        },
        
        async refreshEnrichedModems() {
            // Silently refresh modem list to get enriched data (no loading spinner)
            if (!this.selectedCmts) return;
            
            try {
                let url = `${API_BASE}/cmts/${encodeURIComponent(this.selectedCmts)}/modems?community=${this.snmpCommunity}&limit=10000`;
                if (this.enrichModems) {
                    url += `&enrich=true&modem_community=${this.snmpCommunityModem}`;
                }
                
                const response = await fetch(url);
                const data = await response.json();
                
                if (data.status === 'success' && data.modems) {
                    // Check if we got enriched data (any modem has model)
                    const hasEnrichedData = data.modems.some(m => m.model || m.software_version);
                    if (hasEnrichedData) {
                        this.modems = data.modems.map(m => ({
                            mac_address: m.mac_address,
                            ip_address: m.ip_address,
                            status: m.status || 'unknown',
                            name: m.mac_address,
                            vendor: m.vendor || 'Unknown',
                            model: m.model || 'N/A',
                            docsis_version: m.docsis_version || 'Unknown',
                            cmts: data.cmts_hostname,
                            cmts_ip: data.cmts_ip,
                            cmts_interface: m.interface || m.cmts_index || 'N/A',
                            software_version: m.software_version || '',
                            cable_mac: m.cable_mac || '',
                            upstream_interface: m.upstream_interface || '',
                            fiber_node: m.fiber_node || '',
                            partial_service: Boolean(m.partial_service) && m.partial_service !== 'false' && m.partial_service !== '0'
                        }));
                        this.liveModemSource = `Live data from ${data.cmts_hostname} (${data.cmts_ip}) - ${data.count} modems [enriched ✓]`;
                        console.log('Modem list refreshed with enriched data');
                    }
                }
            } catch (error) {
                console.warn('Silent refresh failed:', error);
            }
        },
        
        async clearCmtsCache() {
            if (!this.selectedCmts) return;
            try {
                const response = await fetch(`${API_BASE}/cmts/${encodeURIComponent(this.selectedCmts)}/cache/clear`, { method: 'POST' });
                const data = await response.json();
                if (data.status === 'success') {
                    this.modems = [];
                    this.liveModemSource = '';
                    this.showSuccess('Cache Cleared', data.message || `Cache cleared for ${this.selectedCmts}`);
                } else {
                    this.showError('Cache Clear Failed', data.message || 'Unknown error');
                }
            } catch (error) {
                this.showError('Cache Clear Failed', error.message);
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
            this.upstreamInterfaces = { loading: false, scqamChannels: [], ofdmaChannels: [] };
            this.utscConfig.rfPortIfindex = null;
            this.usRxmerConfig.ofdmaIfindex = null;
            
            this.currentView = 'modems';
            
            // Load system info and channel stats automatically
            try {
                const promises = [
                    this.loadSystemInfo()
                    // loadChannelStats() is called by loadSystemInfo()
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
            // Redirects to loadChannelStats for compatibility with UI buttons
            if (!this.selectedModem) return;
            this.loadingSystemInfo = true;
            try {
                await this.loadChannelStats();
            } finally {
                this.loadingSystemInfo = false;
            }
        },
        
        // Helper to transform PyPNM channel data (SC-QAM + OFDM)
        transformChannelData(dsData) {
            if (!dsData) return [];
            
            const channels = [];
            
            // Handle flat array from agent (already has type field)
            if (Array.isArray(dsData)) {
                dsData.forEach(ch => {
                    channels.push({
                        channel_id: ch.channel_id,
                        frequency_mhz: ch.frequency_mhz || 0,
                        power_dbmv: ch.power_dbmv || 0,
                        snr_db: ch.snr_db || 0,
                        type: ch.type || 'SC-QAM'
                    });
                });
                return channels;
            }
            
            // Handle SC-QAM data from PyPNM response format
            const scqam = dsData.scqam || {};
            const scqamChannels = scqam.channels || scqam.results || [];
            if (Array.isArray(scqamChannels)) {
                scqamChannels.forEach((ch, idx) => {
                    const entry = ch.entry || ch;
                    // Support both pre-processed (frequency_mhz, power) and raw SNMP fields
                    channels.push({
                        channel_id: ch.channel_id || entry.docsIfDownChannelId || idx + 1,
                        frequency_mhz: ch.frequency_mhz || (entry.docsIfDownChannelFrequency ? entry.docsIfDownChannelFrequency / 1000000 : 0),
                        power_dbmv: ch.power !== undefined ? ch.power : (entry.docsIfDownChannelPower || 0),
                        snr_db: ch.snr !== undefined ? ch.snr : (entry.docsIf3SignalQualityExtRxMER ? entry.docsIf3SignalQualityExtRxMER / 10 : 0),
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
                    // Support power/power_dbmv and mer/mer_db field names
                    const power = ch.power !== undefined ? ch.power : (ch.power_dbmv !== undefined ? ch.power_dbmv : (entry.docsIf31CmDsOfdmChannelPower ? entry.docsIf31CmDsOfdmChannelPower / 10 : null));
                    const mer = ch.mer !== undefined ? ch.mer : (ch.mer_db !== undefined ? ch.mer_db : (entry.docsIf31CmDsOfdmChanMer ? entry.docsIf31CmDsOfdmChanMer / 10 : null));
                    
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
            
            // Handle flat array from agent (already has type field)
            if (Array.isArray(usData)) {
                usData.forEach(ch => {
                    channels.push({
                        channel_id: ch.channel_id,
                        frequency_mhz: ch.frequency_mhz || 0,
                        power_dbmv: ch.power_dbmv || 0,
                        type: ch.type || 'ATDMA'
                    });
                });
                return channels;
            }
            
            // Handle ATDMA data
            const atdma = usData.atdma || {};
            const atdmaChannels = atdma.channels || atdma.results || [];
            if (Array.isArray(atdmaChannels)) {
                atdmaChannels.forEach((ch, idx) => {
                    const entry = ch.entry || ch;
                    // Support both pre-processed (frequency_mhz, power/tx_power) and raw SNMP fields
                    const freq = ch.frequency_mhz || (entry.docsIfUpChannelFrequency ? entry.docsIfUpChannelFrequency / 1000000 : 0);
                    channels.push({
                        channel_id: ch.channel_id || entry.docsIfUpChannelId || idx + 1,
                        frequency_mhz: freq,
                        power_dbmv: ch.tx_power !== undefined ? ch.tx_power : (ch.power !== undefined ? ch.power : (entry.docsIf3CmStatusUsTxPower || 0)),
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
                    // Get values - prefer pre-processed channel data (support both zero_freq_mhz and frequency_mhz)
                    const freq = ch.zero_freq_mhz || ch.frequency_mhz || (entry.docsIf31CmUsOfdmaChanSubcarrierZeroFreq ? entry.docsIf31CmUsOfdmaChanSubcarrierZeroFreq / 1000000 : 0);
                    const numSubcarriers = ch.num_subcarriers || entry.docsIf31CmUsOfdmaChanNumActiveSubcarriers || 0;
                    const subcarrierSpacing = ch.subcarrier_spacing_khz || entry.docsIf31CmUsOfdmaChanSubcarrierSpacing || 50;  // in kHz
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
            
            try {
                // Use PyPNM API for channel stats - correct URL
                const response = await fetch(`${API_BASE}/pypnm/channel-stats/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        modem_ip: this.selectedModem.ip_address,
                        community: this.snmpCommunityModem,
                        cmts_ip: this.selectedModem.cmts_ip,
                        cmts_community: this.selectedModem.cmts_community || this.snmpCommunity
                    })
                });
                
                if (!response.ok) {
                    console.warn('Channel stats endpoint not available');
                    return;
                }
                
                const data = await response.json();
                
                // Store full channel stats for computed properties
                // Check for successful response (status === 0 or has downstream/upstream data)
                if (data.status === 0 || data.downstream || data.upstream) {
                    this.channelStats = data;
                    console.log('Channel stats loaded:', data.downstream?.ofdm?.count, 'OFDM,', data.upstream?.ofdma?.count, 'OFDMA');
                    
                    // Transform to old format for compatibility with existing UI
                    const downstream = [];
                    const upstream = [];
                    
                    // Add SC-QAM channels
                    if (data.downstream?.scqam?.channels) {
                        data.downstream.scqam.channels.forEach(ch => {
                            if (ch.frequency_mhz) {  // Only include channels with valid frequency
                                downstream.push({
                                    channel_id: ch.channel_id,
                                    frequency_mhz: ch.frequency_mhz,
                                    power_dbmv: ch.power,
                                    snr_db: ch.snr || ch.rxmer,
                                    type: 'SC-QAM'
                                });
                            }
                        });
                    }
                    
                    // Add OFDM channels
                    if (data.downstream?.ofdm?.channels) {
                        data.downstream.ofdm.channels.forEach(ch => {
                            downstream.push({
                                channel_id: ch.channel_id,
                                frequency_mhz: ch.plc_freq_mhz || ch.frequency_mhz,
                                power_dbmv: ch.power,
                                snr_db: ch.mer || ch.rxmer || ch.snr_db,
                                type: 'OFDM',
                                bandwidth_mhz: ch.bandwidth_mhz,
                                num_subcarriers: ch.num_subcarriers,
                                profiles: ch.profiles || [],
                                current_profile: ch.current_profile
                            });
                        });
                    }
                    
                    // Add ATDMA channels
                    if (data.upstream?.atdma?.channels) {
                        data.upstream.atdma.channels.forEach(ch => {
                            upstream.push({
                                channel_id: ch.channel_id,
                                frequency_mhz: ch.frequency_mhz,
                                power_dbmv: ch.tx_power,
                                type: 'ATDMA',
                                width_mhz: ch.width_mhz
                            });
                        });
                    }
                    
                    // Add OFDMA channels
                    if (data.upstream?.ofdma?.channels) {
                        data.upstream.ofdma.channels.forEach(ch => {
                            upstream.push({
                                channel_id: ch.channel_id,
                                frequency_mhz: ch.zero_freq_mhz || ch.frequency_mhz,
                                power_dbmv: ch.tx_power_dbmv || ch.tx_power,
                                rx_mer: ch.rx_mer,
                                type: 'OFDMA',
                                bandwidth_mhz: ch.bandwidth_mhz,
                                num_subcarriers: ch.num_subcarriers,
                                // active_iucs = profiles list from backend
                                active_iucs: ch.active_iucs || ch.profiles || [],
                                // iuc_list = same profiles for template badge display
                                iuc_list: ch.iuc_list || ch.active_iucs || ch.profiles || [],
                                current_iuc: ch.current_iuc,
                                iuc_stats: ch.iuc_stats || []
                            });
                        });
                    }
                    
                    // Set systemInfo for compatibility with old UI code
                    this.systemInfo = {
                        downstream: downstream,
                        upstream: upstream,
                        timestamp: data.timestamp || new Date().toISOString()
                    };
                    
                    // Update fiber node if available
                    if (data.fiber_node && this.selectedModem) {
                        this.selectedModem.fiber_node = data.fiber_node;
                    }
                }
                
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
                
                // Render charts after data is loaded
                this.$nextTick(() => {
                    this.drawDsChannelChart();
                    this.drawUsChannelChart();
                });
                
            } catch (error) {
                console.warn('Failed to load channel stats:', error);
                // Don't show error to user, just skip channel stats
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
            try {
                const response = await fetch(`/api/pypnm/upstream/interfaces/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip
                    })
                });
                
                if (!response.ok) {
                    console.warn(`Upstream interfaces endpoint returned ${response.status}`);
                    return;
                }
                
                const result = await response.json();
                if (result.success) {
                    this.upstreamInterfaces.scqamChannels = result.scqam_channels || result.rf_ports || [];
                    this.upstreamInterfaces.ofdmaChannels = result.ofdma_channels || [];
                    
                    // Improved auto-selection logic:
                    // Prefer user selection, else select the channel matching the modem's upstream interface or MAC address
                    if (!this.utscConfig.rfPortIfindex) {
                        let selected = null;
                        // Try SC-QAM channels first
                        if (this.upstreamInterfaces.scqamChannels.length > 0) {
                            if (this.selectedModem && this.selectedModem.upstream_interface) {
                                selected = this.upstreamInterfaces.scqamChannels.find(ch => {
                                    return ch.name === this.selectedModem.upstream_interface || ch.mac === this.selectedModem.mac_address;
                                });
                            }
                            this.utscConfig.rfPortIfindex = selected?.ifindex || this.upstreamInterfaces.scqamChannels[0].ifindex;
                        } else if (this.upstreamInterfaces.ofdmaChannels.length > 0) {
                            // Try OFDMA channels if no SC-QAM
                            if (this.selectedModem && this.selectedModem.upstream_interface) {
                                selected = this.upstreamInterfaces.ofdmaChannels.find(ch => {
                                    return ch.name === this.selectedModem.upstream_interface || ch.mac === this.selectedModem.mac_address;
                                });
                                
                                // Casa: if modem is on OFDMA logical (16M range), map to physical port (4M range)
                                // Mapping: physical_ifindex = logical_ifindex - 12000000
                                if (!selected && this.selectedModem.upstream_interface.includes('OFDMA Upstream')) {
                                    // Try to find physical port by extracting slot/port from "OFDMA Upstream 0/6.0"
                                    const match = this.selectedModem.upstream_interface.match(/(\d+)\/(\d+)\.(\d+)/);
                                    if (match) {
                                        const targetName = `Upstream Physical Interface ${match[1]}/${match[2]}.${match[3]}`;
                                        selected = this.upstreamInterfaces.ofdmaChannels.find(ch => ch.name === targetName);
                                    }
                                }
                            }
                            this.utscConfig.rfPortIfindex = selected?.ifindex || this.upstreamInterfaces.ofdmaChannels[0].ifindex;
                        }
                    }
                    // Improved RxMER OFDMA auto-selection
                    if (this.upstreamInterfaces.ofdmaChannels.length > 0 && !this.usRxmerConfig.ofdmaIfindex) {
                        let selected = null;
                        if (this.selectedModem && this.selectedModem.upstream_interface) {
                            selected = this.upstreamInterfaces.ofdmaChannels.find(ch => {
                                return ch.name === this.selectedModem.upstream_interface || ch.mac === this.selectedModem.mac_address;
                            });
                        }
                        this.usRxmerConfig.ofdmaIfindex = selected?.ifindex || this.upstreamInterfaces.ofdmaChannels[0].ifindex;
                    }
                    
                    console.log('Loaded upstream interfaces:', this.upstreamInterfaces);
                    console.log('UTSC rfPortIfindex set to:', this.utscConfig.rfPortIfindex);
                } else {
                    console.error('Failed to load upstream interfaces:', result.error || result.message);
                }
            } catch (error) {
                console.error('Failed to load upstream interfaces:', error?.message || error || 'Unknown error');
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
                        output_format: this.utscConfig.outputFormat,
                        window_function: this.utscConfig.window,
                        repeat_period_ms: this.utscConfig.repeatPeriodMs,
                        freerun_duration_ms: this.utscConfig.freerunDurationMs,
                        runtime: this.utscConfig.runtime,
                        community: this.snmpCommunityRW  // UTSC needs SNMP write access
                    })
                });
                
                const result = await response.json();
                if (result.success) {
                    const cfgIdx = result.cfg_index;
                    // Valid cfg_index ranges by vendor:
                    //   Casa CCAP   : 1 (row index in cfgTable)
                    //   CommScope / Arris / Cisco : ifIndex-based, typically > 10000
                    // Any positive integer is acceptable; 0 / null / negative is not.
                    if (!cfgIdx || cfgIdx <= 0) {
                        this.$toast?.error(`Configure returned invalid cfg_index: ${cfgIdx}`);
                        result.success = false;
                    } else {
                        this.utscConfig.cfgIndex = cfgIdx;
                        this.$toast?.success(`UTSC configured (cfg_index=${cfgIdx})`);
                    }
                } else {
                    this.$toast?.error(result.error || 'Failed to configure UTSC');
                }
                return result;
            } catch (error) {
                console.error('Configure UTSC error:', error);
                this.$toast?.error('Failed to configure UTSC');
            }
        },
        
        async startUtsc() {
            if (!this.selectedModem || !this.selectedModem.cmts_ip || !this.utscConfig.rfPortIfindex) {
                return;
            }
            
            this.runningUtsc = true;
            this.utscStatus = null;
            
            try {
                // First configure (vendor-aware defaults applied in PyPNM), then start
                const configResult = await this.configureUtsc();
                if (!configResult || !configResult.success) {
                    this.runningUtsc = false;
                    return;
                }
                
                const cfgIndexForStart = this.utscConfig.cfgIndex;
                if (!cfgIndexForStart || cfgIndexForStart <= 0) {
                    this.$toast?.error(`Invalid cfg_index (${cfgIndexForStart}) — cannot start`);
                    this.runningUtsc = false;
                    return;
                }

                const response = await fetch(`/api/pypnm/upstream/utsc/start/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip,
                        rf_port_ifindex: this.utscConfig.rfPortIfindex,
                        cfg_index: cfgIndexForStart,
                        community: this.snmpCommunityRW
                    })
                });
                
                const result = await response.json();
                if (result.success) {
                    this.$toast?.success('UTSC test started');
                    // Poll for status
                    this.pollUtscStatus();
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
                return;
            }
            
            try {
                const response = await fetch(`/api/pypnm/upstream/utsc/stop/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip,
                        rf_port_ifindex: this.utscConfig.rfPortIfindex,
                        community: this.snmpCommunityRW  // UTSC needs SNMP write access
                    })
                });
                
                const result = await response.json();
                this.runningUtsc = false;
                if (result.success) {
                    this.$toast?.success('UTSC test stopped');
                }
            } catch (error) {
                console.error('Stop UTSC error:', error);
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
                        community: this.snmpCommunityRW  // UTSC needs SNMP write access
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
            if (!this.selectedModem || !this.selectedModem.cmts_ip) {
                this.$toast?.error('No CMTS IP available for this modem');
                return;
            }
            // ofdmaIfindex is always an ifIndex-based value (> 10000 for all vendors)
            const ofdmaIdx = this.usRxmerConfig.ofdmaIfindex;
            if (!ofdmaIdx || ofdmaIdx <= 0) {
                this.$toast?.error(`Invalid OFDMA ifIndex (${ofdmaIdx}) — select a valid OFDMA channel first`);
                return;
            }
            
            this.runningUsRxmer = true;
            this.usRxmerStatus = null;
            this.usRxmerCaptures = [];
            this.usRxmerCaptureIndex = 0;
            this.usRxmerCaptureTotal = this.usRxmerConfig.numCaptures;
            this.usRxmerDisplayIndex = 0;
            this.usRxmerPreloadedImage = null;
            
            await this.runUsRxmerCapture();
        },
        
        async runUsRxmerCapture() {
            if (this.usRxmerCaptureIndex >= this.usRxmerCaptureTotal) {
                this.runningUsRxmer = false;
                this.$toast?.success(`All ${this.usRxmerCaptureTotal} captures complete`);
                return;
            }
            
            const captureNum = this.usRxmerCaptureIndex + 1;
            this.usRxmerStatus = { meas_status_name: `Starting capture ${captureNum}/${this.usRxmerCaptureTotal}`, is_busy: true };
            this.usRxmerPollStart = Date.now();
            
            try {
                const response = await fetch(`/api/pypnm/cmts/ofdma/rxmer/start/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip,
                        ofdma_ifindex: this.usRxmerConfig.ofdmaIfindex,
                        community: this.snmpCommunityRW,
                        pre_eq: this.usRxmerConfig.preEq
                    })
                });
                
                const result = await response.json();
                if (result.success) {
                    this.pollUsRxmerStatus();
                } else {
                    this.$toast?.error(result.error || 'Failed to start US RxMER');
                    this.runningUsRxmer = false;
                }
            } catch (error) {
                this.$toast?.error('Failed to start US RxMER');
                this.runningUsRxmer = false;
            }
        },
        
        async pollUsRxmerStatus() {
            if (!this.runningUsRxmer) return;
            
            try {
                const response = await fetch(`/api/pypnm/cmts/ofdma/rxmer/status/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip,
                        ofdma_ifindex: this.usRxmerConfig.ofdmaIfindex,
                        community: this.snmpCommunityRW
                    })
                });
                
                const result = await response.json();
                const captureNum = this.usRxmerCaptureIndex + 1;
                this.usRxmerStatus = {
                    ...result,
                    meas_status_name: `${result.meas_status_name || 'Polling'} (${captureNum}/${this.usRxmerCaptureTotal})`
                };
                
                if (result.is_ready) {
                    await this.fetchUsRxmerData();
                    this.usRxmerCaptureIndex++;
                    // Continue to next capture
                    await this.runUsRxmerCapture();
                } else if (result.is_error) {
                    this.runningUsRxmer = false;
                    this.$toast?.error(`US RxMER capture ${captureNum} failed`);
                } else if (Date.now() - (this.usRxmerPollStart || 0) > 60000) {
                    this.runningUsRxmer = false;
                    this.$toast?.error(`US RxMER capture ${captureNum} timed out`);
                } else {
                    // Keep polling for BUSY, INACTIVE (Cisco transitions through
                    // INACTIVE briefly before going BUSY/SAMPLE_READY), or unknown
                    setTimeout(() => this.pollUsRxmerStatus(), 2000);
                }
            } catch (error) {
                this.runningUsRxmer = false;
            }
        },
        
        async fetchUtscData() {
            if (!this.selectedModem || !this.selectedModem.cmts_ip) {
                return;
            }
            
            try {
                const response = await fetch(`/api/pypnm/upstream/utsc/data/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip,
                        rf_port_ifindex: this.utscConfig.rfPortIfindex,
                        community: this.snmpCommunityRW,  // UTSC needs SNMP write access
                        include_plot: true  // Single-shot: include matplotlib plot
                    })
                });
                
                const result = await response.json();
                
                if (result.success && result.data) {
                    this.utscSpectrumData = result.data;
                    this.$toast?.success('UTSC spectrum data loaded');
                    // Wait for DOM to update, then render chart
                    this.$nextTick(() => this.renderUtscChart());
                } else {
                    this.$toast?.error(result.error || 'Failed to fetch UTSC data');
                }
            } catch (error) {
                console.error('Fetch UTSC data error:', error);
                this.$toast?.error('Failed to fetch UTSC data');
            }
        },
        
        async fetchUsRxmerData() {
            if (!this.selectedModem || !this.selectedModem.cmts_ip) return;
            
            try {
                const response = await fetch(`/api/pypnm/cmts/ofdma/rxmer/data/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip,
                        ofdma_ifindex: this.usRxmerConfig.ofdmaIfindex,
                        community: this.snmpCommunityRW
                    })
                });
                
                const result = await response.json();
                
                if (result.success && result.image_data) {
                    const capture = {
                        index: this.usRxmerCaptureIndex + 1,
                        image_data: result.image_data,
                        timestamp: new Date().toLocaleTimeString(),
                        status: 'complete'
                    };
                    this.usRxmerCaptures.push(capture);
                    this.usRxmerSpectrumData = result.image_data;
                    this.usRxmerDisplayIndex = this.usRxmerCaptures.length - 1;
                } else {
                    this.usRxmerCaptures.push({
                        index: this.usRxmerCaptureIndex + 1,
                        image_data: null,
                        timestamp: new Date().toLocaleTimeString(),
                        status: 'error: ' + (result.error || 'unknown')
                    });
                }
            } catch (error) {
                this.usRxmerCaptures.push({
                    index: this.usRxmerCaptureIndex + 1,
                    image_data: null,
                    timestamp: new Date().toLocaleTimeString(),
                    status: 'error: ' + error.message
                });
            }
        },
        
        showUsRxmerCapture(idx) {
            if (idx >= 0 && idx < this.usRxmerCaptures.length && this.usRxmerCaptures[idx].image_data) {
                this.usRxmerDisplayIndex = idx;
                this.usRxmerSpectrumData = this.usRxmerCaptures[idx].image_data;
            }
        },
        
        // ============================================
        // Pro Spectrum Analyzer Modal
        // ============================================
        
        openSpectrumAnalyzerModal() {
            if (!this.selectedModem) {
                this.$toast?.error('Select a modem first');
                return;
            }
            
            // Show waiting overlay (plain DOM, no Vue binding)
            const overlay = document.getElementById('spectrumWaitOverlay');
            if (overlay) overlay.style.display = 'flex';
            
            const mac = this.selectedModem.mac_address;
            const iframe = document.getElementById('spectrumAnalyzerFrame');
            
            // Set iframe src with all config params (spectrum-analyzer.html reads them)
            // Pass live=1 if UTSC is already running to skip WebSocket re-configuration
            const liveParam = this.runningUtsc ? '&live=1' : '';
            const cfgParams = `&center_freq_hz=${this.utscConfig.centerFreqMhz * 1000000}&span_hz=${this.utscConfig.spanMhz * 1000000}&num_bins=${this.utscConfig.numBins}&output_format=${this.utscConfig.outputFormat}&window=${this.utscConfig.window}&runtime=${this.utscConfig.runtime}`;
            iframe.src = `/spectrum-analyzer?mac=${encodeURIComponent(mac)}&rfport=${this.utscConfig.rfPortIfindex || ''}&cmts=${encodeURIComponent(this.selectedModem.cmts_ip || '')}${liveParam}${cfgParams}`;
            
            // Listen for 'buffering_complete' from iframe to hide waiting overlay
            const bufferListener = (event) => {
                if (event.data && (event.data.type === 'buffering_complete' || event.data.type === 'spectrum_data')) {
                    console.log('[PARENT] Hiding spectrum wait overlay');
                    const ov = document.getElementById('spectrumWaitOverlay');
                    if (ov) ov.style.display = 'none';
                    window.removeEventListener('message', bufferListener);
                }
            };
            window.addEventListener('message', bufferListener);
            // Fallback: hide after 45 seconds regardless
            setTimeout(() => {
                const ov = document.getElementById('spectrumWaitOverlay');
                if (ov) ov.style.display = 'none';
            }, 45000);
            
            // Show the modal
            const modal = new bootstrap.Modal(document.getElementById('spectrumAnalyzerModal'));
            modal.show();
            this.spectrumAnalyzerModalOpen = true;
        },
        
        closeSpectrumAnalyzerModal() {
            const iframe = document.getElementById('spectrumAnalyzerFrame');
            if (iframe) {
                iframe.src = '';
            }
            this.spectrumAnalyzerModalOpen = false;
            const ov = document.getElementById('spectrumWaitOverlay');
            if (ov) ov.style.display = 'none';
            // Stop UTSC when modal is closed so we don't leave a running capture on the CMTS
            if (this.runningUtsc) {
                this.stopUtsc();
            }
        },
        
        renderUtscChart() {
            const data = this.utscSpectrumData;
            if (!data) return;
            
            const canvas = document.getElementById('utscChart');
            if (!canvas) return;
            if (canvas.offsetWidth === 0 || canvas.offsetHeight === 0) return;
            
            let frequencies = data.frequencies || [];
            const amplitudes = data.amplitudes || [];
            
            if (frequencies.length > 0 && frequencies[0] > 1000000) {
                frequencies = frequencies.map(f => f / 1000000);
            }
            
            if (this.utscChartInstance) {
                try { this.utscChartInstance.destroy(); } catch(e) {}
                this.utscChartInstance = null;
            }
            
            this.utscChartInstance = new Chart(canvas, {
                type: 'line',
                data: {
                    labels: frequencies.map(f => typeof f === 'number' ? f.toFixed(1) : f),
                    datasets: [{
                        label: 'Amplitude (dB)',
                        data: amplitudes,
                        borderColor: '#00ff88',
                        backgroundColor: 'rgba(0, 255, 136, 0.1)',
                        borderWidth: 1,
                        pointRadius: 0,
                        fill: true,
                        tension: 0.1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: {
                            title: { display: true, text: 'Frequency (MHz)', color: '#aaa' },
                            ticks: { maxTicksLimit: 10, color: '#aaa' },
                            grid: { color: 'rgba(255,255,255,0.1)' }
                        },
                        y: {
                            title: { display: true, text: 'Amplitude (dB)', color: '#aaa' },
                            ticks: { color: '#aaa' },
                            grid: { color: 'rgba(255,255,255,0.1)' }
                        }
                    }
                }
            });
        },
        
        renderUsRxmerChart() {
            // US RxMER now displays as img tag in HTML, no canvas rendering needed
        },
        
        closeUtscSpectrum() {
            this.utscSpectrumData = null;
            this.closeSpectrumAnalyzerModal();
        },
        
        closeUsRxmerSpectrum() {
            this.usRxmerSpectrumData = null;
            this.usRxmerCaptures = [];
            this.usRxmerDisplayIndex = 0;
            if (this.usRxmerChartInstance) {
                this.usRxmerChartInstance.destroy();
                this.usRxmerChartInstance = null;
            }
        },

        // ============================================
        // Live Spectrum Analyzer with Buffering
        // ============================================
        
        async startLiveSpectrum() {
            if (!this.selectedModem || !this.selectedModem.cmts_ip || !this.utscConfig.rfPortIfindex) {
                this.$toast?.error('Select a modem with RF port first');
                return;
            }
            
            this.liveSpectrumEnabled = true;
            this.liveSpectrumBuffer = [];
            this.liveSpectrumLastFile = null;  // Track last file to skip duplicates
            this.liveSpectrumStats = { captures: 0, lastUpdate: null, avgRefreshMs: 0 };
            
            // Configure UTSC for FreeRunning mode with fast repeat
            this.utscConfig.triggerMode = 2; // FreeRunning
            this.utscConfig.repeatPeriodMs = this.liveSpectrumIntervalMs;
            this.utscConfig.freerunDurationMs = 600000; // 10 min max
            
            try {
                // Configure and start UTSC (vendor-aware defaults applied in PyPNM)
                const liveConfigResult = await this.configureUtsc();
                if (!liveConfigResult || !liveConfigResult.success) {
                    this.liveSpectrumEnabled = false;
                    return;
                }
                
                const liveCfgIndex = this.utscConfig.cfgIndex;
                if (!liveCfgIndex || liveCfgIndex <= 0) {
                    this.$toast?.error(`Invalid cfg_index (${liveCfgIndex}) — cannot start live spectrum`);
                    this.liveSpectrumEnabled = false;
                    return;
                }

                const response = await fetch(`/api/pypnm/upstream/utsc/start/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip,
                        rf_port_ifindex: this.utscConfig.rfPortIfindex,
                        cfg_index: liveCfgIndex,
                        community: this.snmpCommunityRW
                    })
                });
                
                const result = await response.json();
                if (result.success) {
                    this.$toast?.success('Live spectrum started');
                    this.runningUtsc = true;
                    // Start polling for data
                    this.startLiveSpectrumPolling();
                    // Open Pro Spectrum Analyzer
                    this.openSpectrumAnalyzerModal();
                } else {
                    this.$toast?.error(result.error || 'Failed to start live spectrum');
                    this.liveSpectrumEnabled = false;
                }
            } catch (error) {
                console.error('Start live spectrum error:', error);
                this.$toast?.error('Failed to start live spectrum');
                this.liveSpectrumEnabled = false;
            }
        },
        
        startLiveSpectrumPolling() {
            if (this.liveSpectrumIntervalId) {
                clearInterval(this.liveSpectrumIntervalId);
            }
            
            this.liveSpectrumPolling = true;
            
            // Initial fetch after short delay
            setTimeout(() => this.fetchLiveSpectrumData(), 1000);
            
            // Set up polling interval — stop automatically if no longer running
            this.liveSpectrumIntervalId = setInterval(() => {
                if (this.liveSpectrumEnabled && this.runningUtsc) {
                    this.fetchLiveSpectrumData();
                } else {
                    // State was cleared (e.g. modal closed, backend restart) — stop the interval
                    clearInterval(this.liveSpectrumIntervalId);
                    this.liveSpectrumIntervalId = null;
                    this.liveSpectrumPolling = false;
                }
            }, this.liveSpectrumIntervalMs + 100);
        },
        
        async fetchLiveSpectrumData() {
            if (!this.liveSpectrumEnabled || !this.selectedModem) return;
            
            const startTime = Date.now();
            
            try {
                const response = await fetch(`/api/pypnm/upstream/utsc/data/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip,
                        rf_port_ifindex: this.utscConfig.rfPortIfindex,
                        community: this.snmpCommunityRW
                    })
                });
                
                const result = await response.json();
                
                if (result.success && result.data) {
                    // Skip if same file as last poll (no new data)
                    const currentFile = result.data.filename || null;
                    if (currentFile && currentFile === this.liveSpectrumLastFile) {
                        return;  // No new capture yet
                    }
                    this.liveSpectrumLastFile = currentFile;
                    
                    const elapsed = Date.now() - startTime;
                    
                    // Add to buffer
                    const capture = {
                        timestamp: new Date(),
                        amplitudes: result.data.amplitudes || [],
                        frequencies: result.data.frequencies || [],
                        channel_id: result.data.channel_id,
                        center_freq_mhz: result.data.center_freq_mhz,
                        span_mhz: result.data.span_mhz
                    };
                    
                    this.liveSpectrumBuffer.push(capture);
                    
                    // Trim buffer to max size
                    if (this.liveSpectrumBuffer.length > this.liveSpectrumBufferSize) {
                        this.liveSpectrumBuffer.shift();
                    }
                    
                    // Update stats
                    this.liveSpectrumStats.captures++;
                    this.liveSpectrumStats.lastUpdate = new Date().toLocaleTimeString();
                    this.liveSpectrumStats.avgRefreshMs = Math.round(
                        (this.liveSpectrumStats.avgRefreshMs * (this.liveSpectrumStats.captures - 1) + elapsed) / 
                        this.liveSpectrumStats.captures
                    );
                    
                    // Update current data for chart
                    this.utscSpectrumData = result.data;
                    
                    // Update chart in place (don't recreate)
                    this.updateLiveSpectrumChart();
                }
            } catch (error) {
                console.error('Fetch live spectrum error:', error);
            }
        },
        
        updateLiveSpectrumChart() {
            if (!this.utscSpectrumData) return;
            
            const canvas = document.getElementById('utscChart');
            if (!canvas) return;
            
            // Check canvas is visible
            if (canvas.offsetWidth === 0 || canvas.offsetHeight === 0) {
                console.debug('Canvas not visible, skipping chart update');
                return;
            }
            
            const data = this.utscSpectrumData;
            let frequencies = data.frequencies || [];
            const amplitudes = data.amplitudes || data.amplitudes_dbmv || [];
            
            // Convert Hz to MHz if needed
            if (frequencies.length > 0 && frequencies[0] > 1000000) {
                frequencies = frequencies.map(f => f / 1000000);
            }
            
            try {
                if (this.utscChartInstance && this.utscChartInstance.data && this.utscChartInstance.data.datasets && this.utscChartInstance.data.datasets[0]) {
                    // Update existing chart data
                    this.utscChartInstance.data.labels = frequencies.map(f => typeof f === 'number' ? f.toFixed(2) : f);
                    this.utscChartInstance.data.datasets[0].data = amplitudes;
                    this.utscChartInstance.update('none'); // Update without animation
                } else {
                    // Destroy invalid instance if exists
                    if (this.utscChartInstance) {
                        try {
                            this.utscChartInstance.destroy();
                        } catch (e) {
                            console.debug('Chart destroy error:', e);
                        }
                        this.utscChartInstance = null;
                    }
                    // Create new chart
                    this.renderUtscChart();
                }
            } catch (error) {
                console.error('Update chart error:', error);
                // Try to recreate chart on error
                if (this.utscChartInstance) {
                    try {
                        this.utscChartInstance.destroy();
                    } catch (e) {}
                    this.utscChartInstance = null;
                }
            }
        },
        
        stopLiveSpectrum() {
            this.liveSpectrumEnabled = false;
            this.liveSpectrumPolling = false;
            
            if (this.liveSpectrumIntervalId) {
                clearInterval(this.liveSpectrumIntervalId);
                this.liveSpectrumIntervalId = null;
            }
            
            // Stop UTSC capture
            this.stopUtsc();
            
            this.$toast?.info(`Live spectrum stopped. Captured ${this.liveSpectrumStats.captures} frames.`);
        },
        
        clearSpectrumBuffer() {
            this.liveSpectrumBuffer = [];
            this.liveSpectrumLastFile = null;
            this.liveSpectrumStats = { captures: 0, lastUpdate: null, avgRefreshMs: 0 };
        },
        
        getSpectrumBufferSummary() {
            if (this.liveSpectrumBuffer.length === 0) return null;
            
            const first = this.liveSpectrumBuffer[0];
            const last = this.liveSpectrumBuffer[this.liveSpectrumBuffer.length - 1];
            
            return {
                count: this.liveSpectrumBuffer.length,
                startTime: first.timestamp.toLocaleTimeString(),
                endTime: last.timestamp.toLocaleTimeString(),
                duration: Math.round((last.timestamp - first.timestamp) / 1000)
            };
        },

        async runPnmMeasurement(measurementType) {
            if (!this.selectedModem) return;
            
            this.runningTest = true;
            this.showRawData = false;
            
            try {
                const payload = {
                    modem_ip: this.selectedModem.ip_address,
                    community: this.snmpCommunityModem,
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
                        community: this.snmpCommunityModem
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
            
            // Check if we have matplotlib plots - if so, those are shown separately
            const hasPlots = data.plots && data.plots.length > 0;
            
            // For spectrum without matplotlib plots, draw from channel data
            if (type === 'spectrum' && !hasPlots && data.data) {
                this.drawSpectrumFromChannels(data.data);
                return;
            }
            
            // SKIP Chart.js if we have matplotlib plots
            if (type === 'spectrum' && hasPlots) {
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
        
        drawSpectrumFromChannels(data) {
            // Draw spectrum chart from channel-based data (agent pnm_spectrum result)
            const container = document.getElementById('measurement-charts-container');
            if (!container) return;
            
            const dsChannels = data.downstream_channels || [];
            const usChannels = data.upstream_channels || [];
            
            if (dsChannels.length === 0 && usChannels.length === 0) {
                container.innerHTML = '<div class="alert alert-warning"><i class="bi bi-exclamation-triangle me-2"></i>No channel data available.</div>';
                return;
            }
            
            // Sort channels by frequency
            dsChannels.sort((a, b) => (a.frequency_hz || 0) - (b.frequency_hz || 0));
            
            // Create DS chart
            if (dsChannels.length > 0) {
                const chartDiv = document.createElement('div');
                chartDiv.className = 'mb-4';
                chartDiv.innerHTML = `
                    <div class="card shadow-sm">
                        <div class="card-header bg-primary text-white">
                            <h6 class="mb-0"><i class="bi bi-bar-chart me-2"></i>Downstream Channel Power (${dsChannels.length} channels)</h6>
                        </div>
                        <div class="card-body">
                            <canvas id="ds-spectrum-chart" height="200"></canvas>
                        </div>
                    </div>
                `;
                container.appendChild(chartDiv);
                
                const canvas = chartDiv.querySelector('canvas');
                const labels = dsChannels.map(c => (c.frequency_hz / 1e6).toFixed(1) + ' MHz');
                const powerData = dsChannels.map(c => c.power_dbmv);
                
                new Chart(canvas.getContext('2d'), {
                    type: 'bar',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'Power (dBmV)',
                            data: powerData,
                            backgroundColor: powerData.map(p => 
                                p < -10 ? 'rgba(220, 53, 69, 0.7)' :  // Red - too low
                                p > 10 ? 'rgba(255, 193, 7, 0.7)' :   // Yellow - too high
                                'rgba(40, 167, 69, 0.7)'              // Green - good
                            ),
                            borderWidth: 1
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { display: false },
                            title: { display: true, text: 'DS Channel Power by Frequency' }
                        },
                        scales: {
                            x: { title: { display: true, text: 'Frequency' } },
                            y: { 
                                title: { display: true, text: 'Power (dBmV)' },
                                min: -20,
                                max: 20
                            }
                        }
                    }
                });
            }
            
            // Create US power table
            if (usChannels.length > 0) {
                const tableDiv = document.createElement('div');
                tableDiv.className = 'mt-4';
                tableDiv.innerHTML = `
                    <div class="card shadow-sm">
                        <div class="card-header bg-success text-white">
                            <h6 class="mb-0"><i class="bi bi-arrow-up-circle me-2"></i>Upstream TX Power (${usChannels.length} channels)</h6>
                        </div>
                        <div class="card-body">
                            <div class="table-responsive">
                                <table class="table table-sm table-striped">
                                    <thead><tr><th>Channel</th><th>TX Power (dBmV)</th><th>Status</th></tr></thead>
                                    <tbody>
                                        ${usChannels.map(c => `
                                            <tr>
                                                <td>${c.channel_id}</td>
                                                <td>${c.power_dbmv.toFixed(1)}</td>
                                                <td>${c.power_dbmv >= 35 && c.power_dbmv <= 51 ? 
                                                    '<span class="badge bg-success">Good</span>' : 
                                                    c.power_dbmv > 51 ? '<span class="badge bg-warning">High</span>' :
                                                    '<span class="badge bg-danger">Low</span>'}</td>
                                            </tr>
                                        `).join('')}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                `;
                container.appendChild(tableDiv);
            }
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
            
            // Color bars based on US power thresholds
            // Green: 35-49 dBmV (ideal)
            // Yellow: 33-35 or 49-51 dBmV (warning)
            // Red: <33 or >51 dBmV (danger)
            const bgColors = powerData.map(p => {
                if (p === null || p === undefined) return 'rgba(108, 117, 125, 0.7)'; // gray
                if (p < 33 || p > 51) return 'rgba(220, 53, 69, 0.7)'; // red
                if (p < 35 || p > 49) return 'rgba(255, 193, 7, 0.7)'; // yellow
                return 'rgba(25, 135, 84, 0.7)'; // green
            });
            
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
                        y: { 
                            title: { display: true, text: 'Power (dBmV)' }, 
                            min: 0,
                            suggestedMax: 60
                        }
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
