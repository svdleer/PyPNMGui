// PyPNM Web GUI - Main Application

const { createApp } = Vue;

// Get base path from window object (set by backend template)
const BASE_PATH = window.BASE_PATH || '';
const API_BASE = BASE_PATH + '/api';
const GUI_LOCALE = window.GUI_LOCALE || 'en-US';
const GUI_I18N = window.GUI_I18N || {};
const TOPOLOGY_ENABLED = window.ENABLE_TOPOLOGY || false;
const _configuredCmModemLimit = Number.parseInt(window.CM_MODEM_LIMIT, 10);
const CM_MODEM_LIMIT = Math.min(
    Number.isFinite(_configuredCmModemLimit) && _configuredCmModemLimit > 0 ? _configuredCmModemLimit : 50000,
    50000
);
const DEFAULT_VELOCITY_FACTOR = 0.87;
const MIN_VELOCITY_FACTOR = 0.50;
const MAX_VELOCITY_FACTOR = 1.00;

createApp({
    data() {
        return {
            // Navigation
            currentView: 'home',
            showNavbarLogo: true,
            
            // API Status
            apiStatus: 'mock',
            pypnmHealthy: false,
            agentCount: 0,
            hasCmtsAgent: false,   // agent with cmts_reachable capability
            hasCmAgent: false,    // agent with cm_reachable capability
            hasFileAgent: false,  // agent with pnm_file_get capability
            cmtsAgentCount: 0,
            cmAgentCount: 0,
            fileAgentCount: 0,
            
            // Loading state
            isLoading: false,
            modemDetailLoading: false,
            loadingSystemInfo: false,
            runningTest: false,
            activeMeasurement: null,   // which measurement button is running (e.g. 'rxmer', 'us_pre_eq')
            _activeTaskLabel: null,
            _taskGeneration: 0,
            _currentFetchController: null,
            _utscPollTimer: null,
            _usRxmerPollTimer: null,
            _fnScanPollTimer: null,
            _fnScanWaitTimer: null,
            _dsPollTimer: null,
            _fbPollTimer: null,
            _pageLeaveHandler: null,
            
            // Search parameters
            locale: GUI_LOCALE,
            messages: GUI_I18N,
            searchType: 'mac',
            searchValue: '',
            showSearchSuggestions: false,
            searchSeedMacs: [],
            searchSeedIps: [],
            searchSeedFiberNodes: [],
            cpeSearchSuggestions: [],
            _cpeSuggestTimer: null,
            useTopologySearch: false,
            topologyEnabled: TOPOLOGY_ENABLED,
            searchHouseNumber: '',
            customerIdPrefix: 'RES-',
            topologySuggestions: [],
            snmpCommunity: 'public',
            snmpCommunityRW: 'private',
            snmpCommunityModem: '',
            selectedCmts: '',
            selectedInterface: '',
            searchPerformed: false,
            previousView: 'home',
            cmtsSearch: '',
            
            // Data
            modems: [],
            cmtsList: [],
            cmtsListFull: [],  // Full CMTS list for filtering
            cmtsLegacyNameMap: {},
            cmtsInterfaces: [],
            selectedModem: null,
            modemRefreshStatus: null,   // null | 'queued' | 'running' | 'completed' | 'failed'
            modemRefreshRequestId: null,
            modemRefreshError: null,
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
            pnmOutputType: 'json',  // json = interactive Chart.js; archive = Matplotlib/ZIP
            showRawData: false,
            expandedPlotJson: [],
            selectedMeasurementData: null,
            impulseSource: 'fresh',
            impulseDirection: 'both',
            impulseVelocityFactor: DEFAULT_VELOCITY_FACTOR,
            impulseFiles: [],
            impulseFileId: '',
            impulseFilesLoading: false,

            // Upstream PNM (CMTS-side)
            upstreamInterfaces: {
                loading: false,
                scqamChannels: [],   // SC-QAM upstream channels [{ifindex, channel_id, frequency_mhz}]
                ofdmaChannels: []    // OFDMA upstream channels [{ifindex, index}]
            },
            utscConfig: {
                triggerMode: 2,  // 2=FreeRunning, 5=IdleSID, 6=CM_MAC
                centerFreqMhz: 50,
                spanMhz: 80,
                numBins: 800,
                rfPortIfindex: null,
                cfgIndex: 0,              // 0=auto-probe on backend; EVO may use 2/3 instead of 1
                repeatPeriodMs: 400,      // 400ms default - valid for EVO freeRunning (<=300 files)
                freerunDurationMs: 120000, // 120s default - valid Casa/EVO minimum
                outputFormat: 0,          // 0=auto-detect (tries 5 then 2), 5=fftAmplitude (best for visualisation)
                window: 2,                // 2=rectangular (E6000 RRPS HF only supports rectangular; safe default for all vendors)
                runtime: 60               // seconds - streaming runtime¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡€ for spectrum analyzer
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
            utscLastFilename: null,
            usRxmerSpectrumData: null,
            spectrumAnalyzerModalOpen: false,
            usRxmerChartInstance: null,
            // Multi-capture RxMER
            usRxmerCaptures: [],          // [{index, image_data, timestamp, status}]
            showUsRxmerJson: false,
            usRxmerCaptureIndex: 0,       // current capture number
            usRxmerCaptureTotal: 0,       // total captures requested
            usRxmerDisplayIndex: 0,       // which capture is displayed
            usRxmerPreloadedImage: null,  // preloaded next image
            // Compare pre-eq mode
            comparePreEqMode: false,
            usRxmerComparePhase: 0,       // 0=off 1=capturing ON 2=capturing OFF 3=comparing
            usRxmerFilenameOn: null,
            usRxmerFilenameOff: null,
            usRxmerComparisonImage: null,
            usRxmerAnalysis: null,         // FiberNodeAnalysis (comparison or fiber node)
            showComparisonJson: false,
            // Fiber node analysis
            fiberNodeCaptures: [],         // [{cm_mac_address, filename, preeq_enabled}]
            fiberNodeImage: null,
            fiberNodeAnalysis: null,
            runningFiberNode: false,
            // Fiber Node Service Group scan (separate menu)
            fnScanPreparing: false,
            fnScanPreparingMessage: '',
            fnScanCmtsIp: '',
            fnScanCmts: null,
            fnScanCommunity: '',
            fnScanWriteCommunity: '',
            fnScanChannels: [],        // [{ifindex, description, mac_domain}]
            fnScanFiberNodes: [],      // [{name, mac_domain, channels:[]}]
            fnScanChannelsLoading: false,
            fnScanChannelsCached: false,
            fnScanIfindex: '',
            fnScanExtraIfindices: [],  // Additional channels for multi-channel scan
            fnScanFiberNode: '',
            fnScanFN2Name: '',          // Second fiber node name for comparison
            fnScanFN2Ifindex: null,      // Primary channel of FN2 (added to extras)
            fnScanFN2Channels: [],       // All FN2 ifindices tracked for removal
            fnScanPreEq: true,
            fnScanComparePreEq: false, // Capture both ON+OFF for comparison
            fnScanGroupDelay: true,    // Collect ATDMA group delay + plant assessment (default on)
            fnScanMaxModems: 20,
            fnScanRunning: false,
            fnScanResult: null,
            fnImpulseDirection: 'both',
            fnImpulseVelocityFactor: DEFAULT_VELOCITY_FACTOR,
            fnImpulseRunning: false,
            fnImpulseJobId: null,
            fnImpulseProgress: null,
            fnImpulseResult: null,
            fnImpulseChartAvailability: {
                dsFrequency: false,
                dsImpulse: false,
                usFrequency: false,
                usImpulse: false,
            },
            fnScanProgress: null,   // { step, total, modem, modem_idx, modem_total, channel, action, pct, done }
            fnScanId: null,         // UUID sent to backend for progress tracking
            fnScanStartedAt: null,
            fnScanAbortRequested: false,
            fnConfigCollapsed: false,  // Scan Configuration panel folded
            sidebarCollapsed: false, // left sidebar collapsed state
            fnScanImage: null,
            fnScanPlantAssessment: null,  // plant vs in-home assessment from /fiberNode/plant-assessment
            fnScanTapPlotImage: null,     // matplotlib PNG from /fiberNode/tap-plot
            fnScanTapProfile: null,       // chart-ready tap coordinates from existing pre-EQ data
            fnScanModemCount: null,         // Online modem count for selected channel
            fnScanModemCountLoading: false,
            fnScanModemSource: '',          // 'inventory' or 'snmp'
            fnScanModemLoadedAt: null,      // Date when modem list was loaded
            fnScanUseModemSelector: false,
            fnScanModemSearch: '',
            fnScanSelectedModemMacs: [],
            fnScanSelectorRefreshInFlight: false,
            fnScanLastSelectorRefreshAt: 0,
            fnScanSelectorFilterFn: '',
            fnScanSelectorFilterCableMac: '',
            fnScanSelectorFilterGroupAmp: '',
            fnScanSelectorFilterEndAmp: '',
            fnScanSelectorFilterTap: '',
            fnScanSelectorFilterDocsis: '',
            fnScanSelectorFilterVendor: '',
            fnScanSelectorFilterType: '',
            fnScanSelectorFilterImpairment: '',
            fnScanTopologyBridgeNodeId: '',
            fnScanExpectedServingGroup: '',
            fnSelectedMapVisible: false,
            fnSelectedMapPathStatus: {
                loading: false,
                error: '',
                snapshotDate: '',
                pathCount: 0,
                segmentCount: 0,
                missingCoordinateCount: 0,
                unresolvedCount: 0,
            },

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
            liveCachePartial: false,
            liveCacheRefreshing: false,
            liveInventoryComplete: false,
            liveInventoryStale: false,
            liveCapabilityEnriched: false,
            enrichModems: false,
            enrichmentProgress: { current: 0, total: 0 },
            isEnriching: false,    // reactive flag — drives progress bar in card header
            targetedEnrichmentRunning: false,
            targetedEnrichmentProgress: {
                current: 0,
                total: 0,
                failed: 0,
                unresolved: 0,
                scope: '',
                action: '',
                status: 'idle',
            },
            _enrichBatch1Refreshed: false,  // one-time full refresh after first ~200 enriched
            _metadataRefreshTriggeredByCmts: {},
            _forceNextLiveRefreshByCmts: {},
            channelStatsLoading: false,
            channelStatsError: null,
            channelStatsProgress: {
                pct: 0,
                eta: '',
                elapsedSeconds: 0,
                indeterminate: false,
                steps: [],
            },
            _csProgressTimer: null,
            loadProgress: 0,       // 0-100 fake progress for initial CMTS walk screen
            modemPage: 1,
            modemsPerPage: 200,
            modemSortKey: '',
            modemSortDir: 'asc',
            pendingFullLoadUrl: null,
            pendingFullLoadToken: null,
            
            // DS Channel Estimation Suckout Scan (Fiber Node view)
            dsScanRunning:   false,
            dsScanProgress:  null,   // { total, completed, pct, modem, action }
            dsScanResult:    null,    // { total_modems, success_count, modems: [...] }
            dsScanThreshold: 3.0,     // dB below regression = suckout

            dsScanCollapsed: true,    // collapsed by default

            // DS Fullband Spectrum Scan
            fbScanRunning:   false,
            fbScanProgress:  null,
            fbScanResult:    null,   // { total_modems, success_count, modems, detections, plot_png_b64 }
            fbScanCollapsed: true,
            fbScanStrictInChannel: true,  // suppress guard-band false positives

            // Charts
            charts: {},

            // Modem overview filters
            modemFilterFn:       '',   // selected fiber node
            modemFilterCableMac: '',   // selected cable-mac interface
        };
    },
    
    computed: {
        searchPlaceholder() {
            const placeholders = {
                'ip': this.t('placeholder.ip'),
                'cpe_ip': 'IPv4 prefix or complete IPv6 address',
                'mac': this.t('placeholder.mac'),
                'name': this.t('placeholder.name'),
                'fiber_node': 'e.g. FN55',
                'fibernode': 'e.g. ASV-RC0004.ASV-0034-1A',
                'postal_house': 'e.g. 1234AB',
                'customer_id': 'e.g. 10038131'
            };
            return placeholders[this.searchType] || this.t('placeholder.search_value');
        },

        searchSuggestions() {
            if (this.searchType === 'cpe_ip') {
                return (this.cpeSearchSuggestions || []).slice(0, 10);
            }
            if (this.useTopologySearch) {
                return (this.topologySuggestions || []).slice(0, 10);
            }
            const q = (this.searchValue || '').trim();
            if (!q || this.searchType === 'name') return [];

            if (this.searchType === 'fiber_node') {
                const qq = q.toLowerCase();
                return this.searchSeedFiberNodes
                    .filter(v => String(v || '').toLowerCase().includes(qq))
                    .slice(0, 10);
            }

            if (this.searchType === 'ip') {
                const qq = q.toLowerCase();
                return this.searchSeedIps
                    .filter(v => String(v || '').toLowerCase().includes(qq))
                    .slice(0, 10);
            }

            const qn = this.normalizeMacForMatch(q);
            if (!qn) return [];
            return this.searchSeedMacs
                .filter(v => this.normalizeMacForMatch(v).includes(qn))
                .slice(0, 10)
                .map(v => this.formatMacForSearchStyle(v, q));
        },

        // Unique fiber nodes present in loaded modems (for filter dropdown)
        uniqueModemFiberNodes() {
            const vals = this.modems
                .map(m => m.fiber_node)
                .filter(v => v && v.trim() && !v.toLowerCase().startsWith('fn-cable-mac'));
            return [...new Set(vals)].sort();
        },

        // Unique cable-mac interfaces (for filter dropdown)
        uniqueModemCableMacs() {
            const vals = this.modems
                .map(m => (m.cable_mac || '').replace('cable-mac ', '').trim())
                .filter(Boolean);
            return [...new Set(vals)].sort();
        },

        // Modems after fiber-node and cable-mac filters, then sorted
        filteredModems() {
            const filtered = this.modems.filter(m => {
                if (!this._filterBySelectedInterface([m]).length) return false;
                if (this.modemFilterFn) {
                    const selectedFn = String(this.modemFilterFn || '').trim().toLowerCase();
                    const modemFn = String(m.fiber_node || '').trim().toLowerCase();
                    if (modemFn !== selectedFn) return false;
                }
                if (this.modemFilterCableMac) {
                    const cm = (m.cable_mac || '').replace('cable-mac ', '').trim();
                    if (cm !== this.modemFilterCableMac) return false;
                }
                return true;
            });
            if (!this.modemSortKey) return filtered;
            const key = this.modemSortKey;
            const dir = this.modemSortDir === 'asc' ? 1 : -1;
            const _ip2int = v => {
                const parts = String(v || '').split('.');
                if (parts.length !== 4) return 0;
                return parts.reduce((acc, p) => (acc * 256) + (parseInt(p, 10) || 0), 0);
            };
            return [...filtered].sort((a, b) => {
                let va, vb;
                if (key === 'firmware') {
                    va = (a.firmware || a.software_version || '').toLowerCase();
                    vb = (b.firmware || b.software_version || '').toLowerCase();
                } else if (key === 'cable_mac') {
                    va = (a.cable_mac || '').replace('cable-mac ', '').trim().toLowerCase();
                    vb = (b.cable_mac || '').replace('cable-mac ', '').trim().toLowerCase();
                } else if (key === 'ip_address') {
                    return dir * (_ip2int(a.ip_address) - _ip2int(b.ip_address));
                } else {
                    va = String(a[key] || '').toLowerCase();
                    vb = String(b[key] || '').toLowerCase();
                }
                if (va < vb) return -dir;
                if (va > vb) return  dir;
                return 0;
            });
        },

        // Paginated slice of filteredModems
        pagedModems() {
            const start = (this.modemPage - 1) * this.modemsPerPage;
            return this.filteredModems.slice(start, start + this.modemsPerPage);
        },

        totalPages() {
            return Math.max(1, Math.ceil(this.filteredModems.length / this.modemsPerPage));
        },

        targetedEnrichmentPct() {
            const total = Number(this.targetedEnrichmentProgress?.total || 0);
            const current = Number(this.targetedEnrichmentProgress?.current || 0);
            if (!total) return 0;
            return Math.min(100, Math.max(0, Math.round(current * 100 / total)));
        },

        modemTableShowCmts() {
            // Show CMTS column when any modem has a cmts name (multi-CMTS / topology search)
            return (this.modems || []).some(m => m.cmts && m.cmts !== 'unknown');
        },

        visiblePages() {
            const total = this.totalPages;
            const cur = this.modemPage;
            if (total <= 7) return Array.from({length: total}, (_, i) => i + 1);
            if (cur <= 4)          return [1, 2, 3, 4, 5, '...', total];
            if (cur >= total - 3)  return [1, '...', total-4, total-3, total-2, total-1, total];
            return [1, '...', cur-1, cur, cur+1, '...', total];
        },
        
        // Positive channel evidence is monotonic. Legacy false flags are not
        // authoritative and must never override live channel/interface data.
        hasOfdmChannels() {
            const ofdm = this.channelStats?.downstream?.ofdm || {};
            return Number(ofdm.count || 0) > 0 ||
                   (Array.isArray(ofdm.channels) && ofdm.channels.length > 0) ||
                   this.hasPositiveOfdmEvidence(this.selectedModem);
        },

        hasOfdmaChannels() {
            const ofdma = this.channelStats?.upstream?.ofdma || {};
            return Number(ofdma.count || 0) > 0 ||
                   (Array.isArray(ofdma.channels) && ofdma.channels.length > 0) ||
                   (Array.isArray(this.upstreamInterfaces?.ofdmaChannels) && this.upstreamInterfaces.ofdmaChannels.length > 0) ||
                   this.hasPositiveOfdmaEvidence(this.selectedModem);
        },

        selectedDocsisVersion() {
            if (!this.selectedModem) return 'DOCSIS 3.0';
            return this.resolveDocsisVersion({
                ...this.selectedModem,
                ofdm_enabled: this.hasOfdmChannels || this.selectedModem.ofdm_enabled,
                ofdma_enabled: this.hasOfdmaChannels || this.selectedModem.ofdma_enabled,
            }, 'DOCSIS 3.0');
        },
        
        // Partial service is directional; state=none is healthy. Red is
        // reserved for offline modems, while missing evidence stays neutral.
        ofdmStatus() {
            return this.capabilityStatus({
                ...this.selectedModem,
                ofdm_enabled: this.hasOfdmChannels ? true : this.selectedModem?.ofdm_enabled,
                ofdma_enabled: this.hasOfdmaChannels ? true : this.selectedModem?.ofdma_enabled,
            }, 'downstream');
        },

        ofdmaStatus() {
            return this.capabilityStatus({
                ...this.selectedModem,
                ofdma_enabled: this.hasOfdmaChannels ? true : this.selectedModem?.ofdma_enabled,
            }, 'upstream');
        },
        
        // Measurements requiring downstream OFDM
        requiresOfdm() {
            const ofdmRequired = ['rxmer', 'channel_estimation', 'modulation_profile', 'fec_summary', 'histogram', 'constellation'];
            return ofdmRequired.includes(this.pnmMeasurementType);
        },

        fullbandFreqRangeText() {
            const rows = this.fbScanResult?.modems || [];
            const firstOk = rows.find(m => m?.success && Array.isArray(m.frequencies_mhz) && m.frequencies_mhz.length > 1);
            if (!firstOk) return '';
            const freqs = firstOk.frequencies_mhz;
            const minF = Math.min(...freqs);
            const maxF = Math.max(...freqs);
            if (!Number.isFinite(minF) || !Number.isFinite(maxF)) return '';
            return `Frequency span: ${minF.toFixed(1)} - ${maxF.toFixed(1)} MHz`;
        },

        fnScanProgressPct() {
            const pct = Number(this.fnScanProgress?.pct || 0);
            return Number.isFinite(pct) ? Math.min(100, Math.max(0, pct)) : 0;
        },

        fnScanPhaseLabel() {
            const labels = {
                discovery: 'Discovering modems',
                setup: 'Preparing capture',
                capture: 'Capturing RxMER',
                group_delay: 'Collecting group delay',
                retrieval: 'Retrieving files',
                analysis: 'Plotting and analysis',
                complete: 'Complete',
                error: 'Failed',
            };
            return labels[this.fnScanProgress?.phase] || 'Starting scan';
        },

        fnScanEtaText() {
            const p = this.fnScanProgress;
            if (!this.fnScanRunning || !p || !this.fnScanStartedAt) return '';
            const pct = this.fnScanProgressPct;
            if (pct >= 99) return 'Finalizing analysis...';
            if (pct < 3) return 'Estimating time remaining...';

            const elapsedSec = (Date.now() - this.fnScanStartedAt) / 1000;
            const remSec = Math.max(0, Math.round((elapsedSec / pct) * (100 - pct)));
            const mm = Math.floor(remSec / 60);
            const ss = remSec % 60;
            return `ETA ~${mm}:${String(ss).padStart(2, '0')}`;
        },
        
        // Check if selected measurement can run
        canRunMeasurement() {
            if (!this.selectedModem) return false;
            if (this.runningTest) return false;
            if (!this.hasCmAgent) return false;
            // spectrum and us_pre_eq work without OFDM
            if (this.pnmMeasurementType === 'spectrum') return true;
            if (this.pnmMeasurementType === 'us_pre_eq') return this.hasOfdmaChannels;
            // Other measurements require OFDM
            return this.hasOfdmChannels;
        },

        // Fiber node list sorted numerically (FN1, FN2, FN10 not FN1, FN10, FN2)
        fnScanSortedFiberNodes() {
            return [...this.fnScanFiberNodes].sort((a, b) => {
                // Extract numeric part from name (e.g., "FN12" -> 12)
                const numA = parseInt((a.name || '').replace(/\D/g, '')) || 0;
                const numB = parseInt((b.name || '').replace(/\D/g, '')) || 0;
                if (numA !== numB) return numA - numB;
                // Fall back to string comparison if no numbers
                return (a.name || '').localeCompare(b.name || '');
            });
        },

        // Channels filtered by selected fiber node
        fnScanFilteredChannels() {
            if (!this.fnScanFiberNode) {
                // No fiber node selected — show all channels
                return this.fnScanChannels;
            }
            // Find the selected fiber node object
            const fn = this.fnScanFiberNodes.find(f => f.name === this.fnScanFiberNode);
            if (!fn || !fn.channels) {
                return this.fnScanChannels;
            }
            // Return channels belonging to this fiber node from the full list,
            // plus any fn.channels entries not yet in fnScanChannels (instant fill).
            const fnIfindexes = new Set(fn.channels.map(c => c.ifindex));
            const fromFullList = this.fnScanChannels.filter(ch => fnIfindexes.has(ch.ifindex));
            const fullIfindexes = new Set(fromFullList.map(c => c.ifindex));
            const extras = fn.channels.filter(c => !fullIfindexes.has(c.ifindex));
            return [...fromFullList, ...extras];
        },

        fnScanDisplayFiberNode() {
            return this.fnScanFiberNode || this.selectedModem?.fiber_node || this.selectedModem?.fibernode || '';
        },

        fnScanDisplayChannelLabel() {
            if (!this.fnScanIfindex) return 'Select channel...';
            const idx = this._toIfindex(this.fnScanIfindex);
            const ch = (this.fnScanFilteredChannels || []).find(c => this._toIfindex(c?.ifindex) === idx)
                || (this.fnScanChannels || []).find(c => this._toIfindex(c?.ifindex) === idx);
            if (ch?.description) return ch.description;
            const selIdx = this._toIfindex(this.selectedModem?.ofdma_ifindex, this.selectedModem?.upstream_ifindex);
            if (selIdx && selIdx === idx && this.selectedModem?.upstream_interface) {
                return this.selectedModem.upstream_interface;
            }
            return String(this.fnScanIfindex);
        },

        fnScanModemAge() {
            if (!this.fnScanModemLoadedAt) return '';
            const secs = Math.floor((Date.now() - this.fnScanModemLoadedAt.getTime()) / 1000);
            if (secs < 5) return 'just now';
            if (secs < 60) return `${secs}s ago`;
            const mins = Math.floor(secs / 60);
            if (mins < 60) return `${mins}m ago`;
            return `${Math.floor(mins / 60)}h ${mins % 60}m ago`;
        },

        // Get modem count for currently selected channel
        fnScanSelectedChannelModemCount() {
            if (!this.fnScanIfindex) return null;
            const ch = this.fnScanChannels.find(c => c.ifindex == this.fnScanIfindex);
            return ch?.modem_count ?? null;
        },

        // Base pool: operational + MAC + IP, scoped to selected CMTS & FN
        fnScanBaseModems() {
            const fnName = this.fnScanFiberNode;
            const fnObj = (this.fnScanFiberNodes || []).find(f => f.name === fnName);
            const fnNameLc = (fnName || '').trim().toLowerCase();
            const fnMacDomainLc = (fnObj?.mac_domain || '').trim().toLowerCase();
            const selectedNorm = new Set((this.fnScanSelectedModemMacs || [])
                .map(m => this.normalizeMacForMatch(m))
                .filter(Boolean));

            // Expected serving group(s) for the selected FN — set by
            // _enrichFnSelectorTopologyMetadata. Multiple connected_node_ids
            // can share the same serving_group (e.g. GV-0030-1A and GV-0030-1B
            // both on GV-WC0030-DAA001-G001). Match by SG so sister nodes are
            // included.
            const expectedSgs = new Set(
                (this.fnScanExpectedServingGroup || '').split(',')
                    .map(s => s.trim().toLowerCase())
                    .filter(Boolean)
            );

            const matchesSelectedFn = (m) => {
                if (!fnNameLc) return true;
                const modemFn = (m.fiber_node || '').trim().toLowerCase();
                const modemLinkedNode = (m.linked_node_id || m.topology_node_id || '').trim().toLowerCase();

                // Primary match: fiber_node name or linked_node_id
                if (modemFn === fnNameLc) return true;
                if (fnMacDomainLc && modemFn === fnMacDomainLc) return true;
                if (modemLinkedNode === fnNameLc) return true;
                if (modemLinkedNode && modemLinkedNode.startsWith(`${fnNameLc}.`)) return true;

                // Serving-group match: sister topology nodes on the same SG
                // belong to the same fiber node from an RF perspective.
                if (expectedSgs.size > 0) {
                    const modemSg = (m.topology_serving_group || '').trim().toLowerCase();
                    if (modemSg && expectedSgs.has(modemSg)) return true;
                }

                // Fallback: OFDMA ifindex match, but ONLY when modem has no
                // fiber_node — avoids pulling in modems from adjacent FNs that
                // share the same OFDMA channel (same DS segment, different US).
                if (!modemFn) {
                    const selectedIf = this._toIfindex(this.fnScanIfindex);
                    const modemIf = this._toIfindex(m.ofdma_ifindex, m.upstream_ifindex, m.md_if_index, m.upstream_channel_id);
                    if (selectedIf && modemIf && modemIf === selectedIf) return true;
                }

                return false;
            };

            const rows = (this.modems || [])
                .filter(m => {
                    const macNorm = this.normalizeMacForMatch(m?.mac_address || '');
                    const isSelected = macNorm && selectedNorm.has(macNorm);
                    if (!m?.mac_address) return false;
                    // Channel stubs (from loadFnModemCount) only carry MAC/CMTS/FN context,
                    // no IP/status. Keep them visible for selected FN so selector can populate
                    // even when live CMTS cache is partial.
                    if (m._channel_stub) {
                        if (isSelected) return true;
                        if (matchesSelectedFn(m)) return true;
                    }
                    if (!isSelected && !m?.ip_address) return false;
                    if (!isSelected && this.fnScanCmtsIp && m.cmts_ip && m.cmts_ip !== this.fnScanCmtsIp) return false;
                    if (!isSelected && !matchesSelectedFn(m)) return false;
                    if (!isSelected) {
                        const s = (m.status || '').toString().trim().toLowerCase();
                        const onlineStatuses = new Set(['operational', 'online', 'registrationcomplete', 'ipcomplete']);
                        if (!onlineStatuses.has(s)) return false;
                    }
                    return true;
                });

            // CMTS inventory/enrichment can return duplicate rows for the same modem.
            // Keep one row per MAC so selector counts and selection remain accurate.
            const seen = new Set();
            const unique = [];
            for (const m of rows) {
                const mac = (m.mac_address || '').toLowerCase();
                if (!mac || seen.has(mac)) continue;
                seen.add(mac);
                unique.push(m);
            }

            // Mismatch detection: prefer serving_group-based flag set by
            // _enrichFnSelectorTopologyMetadata. Fall back to dominant
            // topology_node_id when serving_group data is unavailable.
            const resolve = (m) => ({
                ...m,
                docsis_version: this.resolveDocsisVersion(m, m.docsis_version || ''),
            });
            const hasSgMismatch = unique.some(m => m._linked_node_mismatch === true);
            if (hasSgMismatch || this.fnScanExpectedServingGroup) {
                // SG-based detection ran — trust its result (even if no mismatches).
                return unique.map(m => resolve(m));
            }
            // Fallback: dominant topology_node_id frequency.
            const nodeFreq = {};
            for (const m of unique) {
                const nid = (m.topology_node_id || '').trim();
                if (nid) nodeFreq[nid] = (nodeFreq[nid] || 0) + 1;
            }
            const dominantNode = Object.entries(nodeFreq).sort((a, b) => b[1] - a[1])[0]?.[0] || '';
            return unique.map(m => {
                const nid = (m.topology_node_id || '').trim();
                return { ...resolve(m), _linked_node_mismatch: !!(dominantNode && nid && nid !== dominantNode) };
            });
        },

        fnScanUniqueSelectorFiberNodes() {
            const vals = this.fnScanBaseModems
                .map(m => m.fiber_node)
                .filter(v => v && v.trim());
            return [...new Set(vals)].sort();
        },

        fnScanUniqueSelectorCableMacs() {
            const vals = this.fnScanBaseModems
                .map(m => (m.cable_mac || '').replace(/^cable-mac\s*/i, '').trim())
                .filter(Boolean);
            return [...new Set(vals)].sort();
        },

        fnScanUniqueSelectorGroupAmps() {
            const vals = this.fnScanBaseModems
                .filter(m => !m._linked_node_mismatch)
                .map(m => this.formatTopologyGroupAmplifier(m.topology_group_amplifier))
                .filter(v => v && v.trim());
            return [...new Set(vals)].sort();
        },

        fnScanUniqueSelectorEndAmps() {
            const vals = this.fnScanBaseModems
                .filter(m => !m._linked_node_mismatch)
                .map(m => this.formatTopologyEndAmplifier(m.topology_end_amplifier))
                .filter(v => v && v.trim());
            return [...new Set(vals)].sort();
        },

        fnScanUniqueSelectorTaps() {
            const vals = this.fnScanBaseModems
                .filter(m => !m._linked_node_mismatch)
                .map(m => this.formatTopologyTap(m.topology_tap))
                .filter(v => v && v.trim());
            return [...new Set(vals)].sort();
        },

        fnScanUniqueSelectorDocsisVersions() {
            const vals = this.fnScanBaseModems.map(m => this.fnSelectorDocsisValue(m));
            return [...new Set(vals)].sort((a, b) =>
                this.docsisVersionRank(b) - this.docsisVersionRank(a) || a.localeCompare(b)
            );
        },

        fnScanUniqueSelectorVendors() {
            const vals = this.fnScanBaseModems.map(m => this.fnSelectorVendorValue(m));
            return [...new Set(vals)].sort((a, b) => a.localeCompare(b));
        },

        fnScanUniqueSelectorTypes() {
            const vals = this.fnScanBaseModems.map(m => this.fnSelectorTypeValue(m));
            return [...new Set(vals)].sort((a, b) => a.localeCompare(b));
        },

        fnScanHasSelectorFilters() {
            return [
                this.fnScanSelectorFilterFn,
                this.fnScanSelectorFilterCableMac,
                this.fnScanSelectorFilterGroupAmp,
                this.fnScanSelectorFilterEndAmp,
                this.fnScanSelectorFilterTap,
                this.fnScanSelectorFilterDocsis,
                this.fnScanSelectorFilterVendor,
                this.fnScanSelectorFilterType,
                this.fnScanSelectorFilterImpairment,
                this.fnScanModemSearch,
            ].some(value => String(value || '').trim());
        },

        fnScanDominantNodeId() {
            const freq = {};
            for (const m of this.fnScanBaseModems) {
                const nid = (m.topology_node_id || '').trim();
                if (nid) freq[nid] = (freq[nid] || 0) + 1;
            }
            return Object.entries(freq).sort((a, b) => b[1] - a[1])[0]?.[0] || '';
        },

        fnScanDetectedNodes() {
            const freq = {};
            for (const m of this.fnScanBaseModems) {
                if (m._linked_node_mismatch) continue;
                const nid = (m.topology_node_id || '').trim();
                if (nid) freq[nid] = (freq[nid] || 0) + 1;
            }
            return Object.entries(freq)
                .sort((a, b) => b[1] - a[1])
                .map(([node, count]) => ({ node, count }));
        },

        fnScanMismatchCount() {
            return this.fnScanBaseModems.filter(m => m._linked_node_mismatch).length;
        },

        fnScanMaxSelectableModems() {
            const n = parseInt(this.fnScanMaxModems, 10);
            return Number.isFinite(n) && n > 0 ? n : 20;
        },

        fnScanSelectedDocsis30Count() {
            const selected = new Set((this.fnScanSelectedModemMacs || []).map(m => this.normalizeMacForMatch(m)).filter(Boolean));
            if (!selected.size) return 0;
            let count = 0;
            for (const modem of (this.fnScanFilteredModems || [])) {
                const mac = this.normalizeMacForMatch(modem?.mac_address || '');
                if (!mac || !selected.has(mac)) continue;
                const docsis = this.resolveDocsisVersion(modem, 'Unknown');
                if (this.docsisVersionRank(docsis) === 30) count += 1;
            }
            return count;
        },

        fnImpulseMissingCapturePlan() {
            const plan = [];
            for (const modem of (this.fnImpulseResult?.modems || [])) {
                const macAddress = String(modem?.mac_address || '').trim();
                if (!macAddress) continue;
                for (const state of (modem?.direction_statuses || [])) {
                    if (state?.status !== 'missing') continue;
                    if (!['downstream', 'upstream'].includes(state?.direction)) continue;
                    plan.push({ mac_address: macAddress, direction: state.direction });
                }
            }
            return plan;
        },

        fnImpulseMissingCounts() {
            return this.fnImpulseMissingCapturePlan.reduce((counts, item) => {
                if (item.direction === 'downstream') counts.downstream += 1;
                if (item.direction === 'upstream') counts.upstream += 1;
                return counts;
            }, { downstream: 0, upstream: 0 });
        },

        fnScanFilteredModems() {
            const q = (this.fnScanModemSearch || '').toLowerCase().trim();
            const filterFn = this.fnScanUniqueSelectorFiberNodes.includes(this.fnScanSelectorFilterFn)
                ? this.fnScanSelectorFilterFn
                : '';
            const filterCm = this.fnScanUniqueSelectorCableMacs.includes(this.fnScanSelectorFilterCableMac)
                ? this.fnScanSelectorFilterCableMac
                : '';
            const filterGa = this.fnScanUniqueSelectorGroupAmps.includes(this.fnScanSelectorFilterGroupAmp)
                ? this.fnScanSelectorFilterGroupAmp
                : '';
            const filterEa = this.fnScanUniqueSelectorEndAmps.includes(this.fnScanSelectorFilterEndAmp)
                ? this.fnScanSelectorFilterEndAmp
                : '';
            const filterTap = this.fnScanUniqueSelectorTaps.includes(this.fnScanSelectorFilterTap)
                ? this.fnScanSelectorFilterTap
                : '';
            const filterDocsis = this.fnScanUniqueSelectorDocsisVersions.includes(this.fnScanSelectorFilterDocsis)
                ? this.fnScanSelectorFilterDocsis
                : '';
            const filterVendor = this.fnScanUniqueSelectorVendors.includes(this.fnScanSelectorFilterVendor)
                ? this.fnScanSelectorFilterVendor
                : '';
            const filterType = this.fnScanUniqueSelectorTypes.includes(this.fnScanSelectorFilterType)
                ? this.fnScanSelectorFilterType
                : '';
            const validImpairmentFilters = new Set(['impaired_ofdma', 'impaired_ofdm', 'impaired_any']);
            const filterImpairment = validImpairmentFilters.has(this.fnScanSelectorFilterImpairment)
                ? this.fnScanSelectorFilterImpairment
                : '';

            const filtered = this.fnScanBaseModems
                .filter(m => {
                    if (filterFn) {
                        const selectedFn = String(filterFn || '').trim().toLowerCase();
                        const modemFn = String(m.fiber_node || '').trim().toLowerCase();
                        if (modemFn !== selectedFn) return false;
                    }
                    if (filterCm) {
                        const cm = (m.cable_mac || '').replace(/^cable-mac\s*/i, '').trim();
                        if (cm !== filterCm) return false;
                    }
                    if (filterGa && this.formatTopologyGroupAmplifier(m.topology_group_amplifier) !== filterGa) return false;
                    if (filterEa && this.formatTopologyEndAmplifier(m.topology_end_amplifier) !== filterEa) return false;
                    if (filterTap && this.formatTopologyTap(m.topology_tap) !== filterTap) return false;
                    if (filterDocsis && this.fnSelectorDocsisValue(m) !== filterDocsis) return false;
                    if (filterVendor && this.fnSelectorVendorValue(m) !== filterVendor) return false;
                    if (filterType && this.fnSelectorTypeValue(m) !== filterType) return false;
                    if (filterImpairment) {
                        const ofdmImpaired = this.isDirectionalPartialService(m, 'downstream');
                        const ofdmaImpaired = this.isDirectionalPartialService(m, 'upstream');
                        if (filterImpairment === 'impaired_ofdma' && !ofdmaImpaired) return false;
                        if (filterImpairment === 'impaired_ofdm' && !ofdmImpaired) return false;
                        if (filterImpairment === 'impaired_any' && !(ofdmImpaired || ofdmaImpaired)) return false;
                    }
                    if (!q) return true;
                    return (
                        (m.mac_address || '').toLowerCase().includes(q) ||
                        (m.ip_address || '').toLowerCase().includes(q) ||
                        (m.vendor || '').toLowerCase().includes(q) ||
                        (m.model || '').toLowerCase().includes(q) ||
                        (m.docsis_version || '').toLowerCase().includes(q) ||
                        (m.upstream_interface || '').toLowerCase().includes(q) ||
                        (m.fiber_node || '').toLowerCase().includes(q) ||
                        (m.cable_mac || '').toLowerCase().includes(q) ||
                        (m.topology_group_amplifier || '').toLowerCase().includes(q) ||
                        (m.topology_end_amplifier || '').toLowerCase().includes(q) ||
                        (m.topology_tap || '').toLowerCase().includes(q)
                    );
                });
            const selectedSet = new Set((this.fnScanSelectedModemMacs || [])
                .map(m => this.normalizeMacForMatch(m))
                .filter(Boolean));

            return filtered.sort((a, b) => {
                const aSel = selectedSet.has(this.normalizeMacForMatch(a.mac_address || '')) ? 1 : 0;
                const bSel = selectedSet.has(this.normalizeMacForMatch(b.mac_address || '')) ? 1 : 0;
                return bSel - aSel;
            });
        },

        fnScanCandidateModems() {
            // Keep rendering fast for large FN inventories.
            // Sort mismatched modems to the bottom so they're visible.
            const all = this.fnScanFilteredModems;
            const normal = all.filter(m => !m._linked_node_mismatch);
            const mismatched = all.filter(m => m._linked_node_mismatch);
            return [...normal, ...mismatched].slice(0, this.fnScanSelectorDisplayLimit);
        },

        fnScanSelectorDisplayLimit() {
            const n = Number(this.fnScanModemCount ?? this.fnScanSelectedChannelModemCount ?? 0);
            const base = (Number.isFinite(n) && n > 0) ? n : 300;
            // Add headroom for mismatched modems that are sorted to the bottom.
            return Math.max(base, 300) + 50;
        },

        fnScanSelectedModemCount() {
            return (this.fnScanSelectedModemMacs || []).length;
        },

        fnScanSelectedMappableModems() {
            const selected = new Set((this.fnScanSelectedModemMacs || [])
                .map(mac => this.normalizeMacForMatch(mac))
                .filter(Boolean));
            const seen = new Set();
            const points = [];
            for (const modem of (this.fnScanBaseModems || [])) {
                const mac = this.normalizeMacForMatch(modem?.mac_address);
                if (!mac || !selected.has(mac) || seen.has(mac)) continue;
                seen.add(mac);
                const coordinates = this.modemCoordinates(modem);
                if (!coordinates) continue;
                points.push({ ...modem, coordinates });
            }
            return points;
        },

        fnScanSelectedMissingCoordinatesCount() {
            return Math.max(0, this.fnScanSelectedModemCount - this.fnScanSelectedMappableModems.length);
        },

        fnScanScopeLabel() {
            return this.fnScanUseModemSelector ? 'Scope: Selected Modems' : 'Scope: Full FiberNode';
        },

        fnScanScopeBadgeClass() {
            return this.fnScanUseModemSelector ? 'bg-primary' : 'bg-success';
        },

        fnScanScopeCount() {
            if (this.fnScanUseModemSelector) {
                return this.fnScanSelectedModemCount;
            }
            const n = Number(this.fnScanModemCount ?? this.fnScanSelectedChannelModemCount ?? 0);
            return Number.isFinite(n) && n > 0 ? n : 0;
        },

        fnScanEstimatedChannels() {
            return (this.fnScanIfindex ? 1 : 0) + (this.fnScanExtraIfindices?.length || 0);
        },

        fnScanEstimatedModes() {
            return this.fnScanComparePreEq ? 2 : 1;
        },

        fnScanEstimatedModems() {
            if (this.fnScanUseModemSelector && this.fnScanSelectedModemCount > 0) {
                return this.fnScanSelectedModemCount;
            }
            const selected = Number(this.fnScanModemCount);
            const maxCfg = Math.max(2, parseInt(this.fnScanMaxModems) || 20);
            if (Number.isFinite(selected) && selected > 0) return Math.min(selected, maxCfg);
            return maxCfg;
        },

        fnScanEstimatedSteps() {
            const ch = this.fnScanEstimatedChannels;
            if (!ch) return 0;
            return this.fnScanEstimatedModems * ch * this.fnScanEstimatedModes;
        },

        fnScanPreEtaText() {
            const steps = this.fnScanEstimatedSteps;
            if (!steps) return '';
            // Empirical median around 14-16s per capture step on current hardware path.
            const secPerStep = 15;
            const totalSec = steps * secPerStep;
            const mm = Math.floor(totalSec / 60);
            const ss = totalSec % 60;
            return `Expected workload: ~${steps} captures (${this.fnScanEstimatedModems} modems x ${this.fnScanEstimatedChannels} channel(s) x ${this.fnScanEstimatedModes} mode(s))  ·  ETA ~${mm}:${String(ss).padStart(2, '0')}`;
        }
    },
    
    async mounted() {
        // Restore sidebar collapsed state
        const saved = localStorage.getItem('sidebarCollapsed');
        if (saved !== null) this.sidebarCollapsed = saved === 'true';
            const params = new URLSearchParams(window.location.search || '');
            const requestedView = (params.get('view') || '').trim();
            if (['home', 'modems', 'fibernode'].includes(requestedView)) {
                this.currentView = requestedView;
                params.delete('view');
                const newQuery = params.toString();
                const newUrl = `${window.location.pathname}${newQuery ? '?' + newQuery : ''}${window.location.hash || ''}`;
                window.history.replaceState({}, '', newUrl);
            }

        // Check API health
        await this.checkApiHealth();
        
        // Load community strings from server config
        await this.loadConfig();
        
        // Load CMTS list
        await this.loadCmtsList();

        // Warm up MAC/IP suggestion cache for search box.
        await this.preloadSearchSeed();
        
        // Don't load mock modems - only show live data from CMTS
        // await this.searchModems();

        this._pageLeaveHandler = () => {
            this.cancelActiveUiTasks({ silent: true, stopBackend: false });
        };
        window.addEventListener('pagehide', this._pageLeaveHandler);
        window.addEventListener('beforeunload', this._pageLeaveHandler);

        // Auto-stop UTSC whenever the spectrum analyzer modal is fully closed
        // (covers X button, Escape key, and backdrop click)
        const saModal = document.getElementById('spectrumAnalyzerModal');
        if (saModal) {
            saModal.addEventListener('hidden.bs.modal', () => {
                if (this.spectrumAnalyzerModalOpen) {
                    this.closeSpectrumAnalyzerModal();
                }
            });
        }
    },

    beforeUnmount() {
        if (this._pageLeaveHandler) {
            window.removeEventListener('pagehide', this._pageLeaveHandler);
            window.removeEventListener('beforeunload', this._pageLeaveHandler);
        }
        this.cancelActiveUiTasks({ silent: true, stopBackend: false });
        Object.values(this.charts || {}).forEach(chart => {
            try { chart?.destroy(); } catch (_) {}
        });
        this._dsHeatmapResizeObserver?.disconnect();
        this._dsHeatmapResizeObserver = null;
        this._destroyFnSelectedMap();
        this.charts = {};
    },

    watch: {
        sidebarCollapsed(val) {
            localStorage.setItem('sidebarCollapsed', val);
        },
        fnScanSelectedMappableModems: {
            deep: true,
            handler(points) {
                if (!this.fnSelectedMapVisible) return;
                if (!points.length) {
                    this.fnSelectedMapVisible = false;
                    this._destroyFnSelectedMap();
                    return;
                }
                this.$nextTick(() => this._scheduleFnSelectedMapRender());
            },
        },
        fnImpulseResult: {
            deep: true,
            handler() {
                if (this.fnSelectedMapVisible) {
                    this.$nextTick(() => this._scheduleFnSelectedMapRender());
                }
            },
        },
        fnScanUseModemSelector(newVal) {
            if (!newVal) {
                this.fnSelectedMapVisible = false;
                this._destroyFnSelectedMap();
                return;
            }
            // Keep titlebar filters at explicit user choice; do not auto-apply FN filter.
            if (this.fnScanCandidateModems.length === 0) {
                // Force refresh when enabling selector so list is populated immediately.
                this.refreshFnSelectorModems(true);
            }
        },
        fnConfigCollapsed(collapsed) {
            if (collapsed) {
                this.fnSelectedMapVisible = false;
                this._destroyFnSelectedMap();
            }
        },
        modemPage(newPage) {
            if (newPage > 1) this._maybeStartDeferredFullLoad();
        },
        selectedInterface() {
            this.modemPage = 1;
        },
        modemFilterFn() {
            this.modemPage = 1;
        },
        modemFilterCableMac() {
            this.modemPage = 1;
        },
        totalPages(newTotal) {
            if (this.modemPage > newTotal) this.modemPage = newTotal;
        },
        fnScanMaxModems() {
            const maxAllowed = this.fnScanMaxSelectableModems;
            const current = [...(this.fnScanSelectedModemMacs || [])];
            if (current.length > maxAllowed) {
                this.fnScanSelectedModemMacs = current.slice(0, maxAllowed);
                this.$toast?.warning(`Selection capped at ${maxAllowed} modems.`);
            }
        },
        currentView(newView, oldView) {
            if (oldView && newView !== oldView) {
                this.previousView = oldView;
                this.cancelActiveUiTasks({ silent: true, stopBackend: false });
            }
            if (oldView === 'fibernode' && newView !== 'fibernode') {
                this.fnSelectedMapVisible = false;
                this._destroyFnSelectedMap();
            }
            if (newView === 'fibernode') {
                // If user enters FiberNode from main menu with a CMTS selected on Home,
                // bootstrap FN context automatically so scanner is immediately usable.
                if (!this.fnScanCmtsIp && this.selectedCmts) {
                    const cmtsMatch = this.findCmtsMatch(this.selectedCmts, this.selectedCmts);
                    if (cmtsMatch?.ip) {
                        this.selectFnScanCmts(cmtsMatch);
                    }
                }
                if (this.selectedModem?.mac_address && (this.selectedModem?.cmts_ip || this.selectedModem?.cmts || this.selectedModem?.cmts_hostname)) {
                    console.log('[watcher] triggering primeFnScanFromSelectedModem() for fibernode view');
                    this.primeFnScanFromSelectedModem(this.selectedModem).catch(err => {
                        console.warn('[watcher] fibernode priming failed:', err?.message || err);
                    });
                }
                return;
            }
            // Load UTSC/US RxMER ifIndex data when user opens Measurements tab.
            console.log('[watcher] currentView changed to:', newView,
                        '| selectedModem:', this.selectedModem?.mac_address,
                        '| cmts_ip:', this.selectedModem?.cmts_ip,
                        '| us.loading:', this.upstreamInterfaces?.loading);

            if (newView !== 'measurements') return;
            if (!this.selectedModem) {
                console.warn('[watcher] no selectedModem — skipping upstream load');
                return;
            }

            // Always refresh upstream selectors on tab open so stale/missing
            // ifIndex values don't leave UTSC/US RxMER unusable.
            if (this.selectedModem.cmts_ip && !this.upstreamInterfaces.loading) {
                console.log('[watcher] triggering loadUpstreamInterfaces()');
                this.loadUpstreamInterfaces();
            } else {
                console.warn('[watcher] skipped loadUpstreamInterfaces —',
                             'cmts_ip:', this.selectedModem.cmts_ip,
                             'loading:', this.upstreamInterfaces.loading);
            }

            // Also load channel/system info when entering PNM tab.
            if (!this.loadingSystemInfo && !this.channelStatsLoading && !this.channelStats) {
                console.log('[watcher] triggering loadSystemInfo()');
                this.loadSystemInfo();
            }
        },
    },

    methods: {
        // ============== Utility Methods ==============

        _validVelocityFactor(value) {
            const velocityFactor = Number(value);
            if (!Number.isFinite(velocityFactor)) return null;
            if (velocityFactor < MIN_VELOCITY_FACTOR || velocityFactor > MAX_VELOCITY_FACTOR) return null;
            return velocityFactor;
        },

        formatVelocityFactor(value) {
            const velocityFactor = this._validVelocityFactor(value);
            if (velocityFactor === null) return 'Invalid (0.50–1.00)';
            return `${velocityFactor.toFixed(2)} / ${(velocityFactor * 100).toFixed(0)}%`;
        },

        clampVelocityFactor(fieldName) {
            const parsed = Number(this[fieldName]);
            const velocityFactor = Number.isFinite(parsed)
                ? Math.min(MAX_VELOCITY_FACTOR, Math.max(MIN_VELOCITY_FACTOR, parsed))
                : DEFAULT_VELOCITY_FACTOR;
            this[fieldName] = Number(velocityFactor.toFixed(2));
        },

        requireVelocityFactor(value) {
            const velocityFactor = this._validVelocityFactor(value);
            if (velocityFactor === null) {
                this.$toast?.error('VOP must be a finite value from 0.50 through 1.00');
            }
            return velocityFactor;
        },

        t(key, fallback = null) {
            if (this.messages && Object.prototype.hasOwnProperty.call(this.messages, key)) {
                return this.messages[key];
            }
            return fallback ?? key;
        },

        normalizePartialService(value) {
            if (value === true) return true;
            if (value === false || value == null) return false;
            if (typeof value === 'number') {
                return value === 1 || (value >= 3 && value <= 5);
            }
            const normalized = String(value).trim().toLowerCase();
            return ['1', 'true', 'yes', 'on', '3', '4', '5'].includes(normalized);
        },

        partialServiceDirectionKnown(modem) {
            return modem?.partial_service_downstream != null || modem?.partial_service_upstream != null;
        },

        isDirectionalPartialService(modem, direction) {
            // Recognized DOCS-IF31 state values are authoritative, even when
            // directional booleans contain stale data.
            const state = String(modem?.partial_service_state || '').trim().toLowerCase();
            if (state === 'none' || state === 'other') return false;
            if (['downstream', 'upstream', 'both'].includes(state)) {
                return state === 'both' || state === direction;
            }

            const field = direction === 'downstream'
                ? modem?.partial_service_downstream
                : modem?.partial_service_upstream;
            if (field != null) return this.normalizePartialService(field);
            return false;
        },

        isUndirectedPartialService(modem) {
            if (this.partialServiceDirectionKnown(modem)) return false;
            const state = String(modem?.partial_service_state || '').trim().toLowerCase();
            // Directional states are handled by isDirectionalPartialService and
            // must not also produce the generic undirected PS warning.
            if (['downstream', 'upstream', 'both', 'none', 'other'].includes(state)) return false;
            return this.normalizePartialService(modem?.partial_service);
        },

        setModemSort(key) {
            if (this.modemSortKey === key) {
                this.modemSortDir = this.modemSortDir === 'asc' ? 'desc' : 'asc';
            } else {
                this.modemSortKey = key;
                this.modemSortDir = 'asc';
            }
            this.modemPage = 1;
        },

        normalizeMacForMatch(value) {
            return String(value || '').toLowerCase().replace(/[^a-f0-9]/g, '');
        },

        formatMacForSearchStyle(value, reference) {
            const clean = this.normalizeMacForMatch(value);
            if (!clean) return String(value || '');

            const style = String(reference || '');
            if (style.includes('.')) return clean.match(/.{1,4}/g).join('.');
            if (style.includes('-')) return clean.match(/.{1,2}/g).join('-');
            if (style.includes(':')) return clean.match(/.{1,2}/g).join(':');
            return clean;
        },

        normalizeMacForDisplay(value) {
            const clean = String(value || '').replace(/[^a-fA-F0-9]/g, '').toLowerCase();
            if (clean.length !== 12) return String(value || '');
            return clean.match(/.{1,2}/g).join(':');
        },

        normalizeCmtsName(value) {
            const raw = String(value || '').trim().toUpperCase();
            if (!raw) return '';
            const withoutCountryPrefix = raw.replace(/^[A-Z]{2}-/, '');
            return withoutCountryPrefix.replace(/^([A-Z]{2})-([A-Z]{3}-LC\d{4}-CCAP\d{3,})$/, '$2');
        },

        findCmtsMatch(cmtsIp, cmtsName) {
            const candidates = this.cmtsListFull || [];
            const wantedIp = String(cmtsIp || '').trim();

            // IP is authoritative. Do not let a lossy legacy-name match select a
            // different CMTS before the exact IP appears later in the list.
            if (wantedIp) {
                const ipMatch = candidates.find(c => String(c?.ip || '').trim() === wantedIp);
                if (ipMatch) return ipMatch;
            }

            // Preserve full hostnames before applying legacy normalization. Names
            // such as HL-LC0001-CCAP001 and BV-LC0001-CCAP001 otherwise both
            // normalize to LC0001-CCAP001.
            const wantedFullName = String(cmtsName || '').trim().toUpperCase();
            if (wantedFullName) {
                const nameMatch = candidates.find(c =>
                    String(c?.name || '').trim().toUpperCase() === wantedFullName
                );
                if (nameMatch) return nameMatch;
            }

            const wantedName = this.normalizeCmtsName(cmtsName);
            const canonicalWantedName = this.cmtsLegacyNameMap[wantedName] || wantedName;
            return candidates.find(c => {
                const candidateName = this.normalizeCmtsName(c?.name || '');
                return canonicalWantedName && candidateName === canonicalWantedName;
            }) || null;
        },

        resolveCanonicalCmtsDisplayName(cmtsIp, cmtsName) {
            const match = this.findCmtsMatch(cmtsIp, cmtsName);
            if (match?.name) return match.name;

            const normalized = this.normalizeCmtsName(cmtsName);
            if (/(ABR|DBR|CBR)\d+$/i.test(normalized)) return '';
            return String(cmtsName || '').trim();
        },

        _isIdentityPlaceholder(value) {
            const text = String(value ?? '').trim().toLowerCase();
            return ['', 'unknown', 'n/a', 'na', 'none', 'null', '-', '—'].includes(text);
        },

        _mergeModemPreservingCmts(target, source) {
            if (!target || !source) return target;

            // Merge ordinary fields normally, but capability evidence is
            // monotonic: positive evidence and richer indexes/channel rows
            // cannot be erased by stale false, empty, or nonpositive values.
            const before = { ...target };
            const preserve = [
                'cmts', 'cmts_ip', 'cmts_hostname', 'cmts_community',
                'fiber_node', 'cable_mac', 'upstream_interface',
            ];
            const saved = {};
            for (const key of preserve) {
                if (before[key] && (!source[key] || source[key] === 'unknown' || source[key] === 'N/A')) {
                    saved[key] = before[key];
                }
            }
            // A non-enriched cache row must not replace identity data obtained
            // by a completed targeted refresh.
            for (const key of ['vendor', 'model', 'software_version', 'firmware']) {
                if (!this._isIdentityPlaceholder(before[key]) && this._isIdentityPlaceholder(source[key])) {
                    saved[key] = before[key];
                }
            }

            const indexFields = [
                'ofdm_ifindex', 'ofdm_rf_port_ifindex', 'downstream_ofdm_ifindex',
                'ofdma_ifindex', 'ofdma_rf_port_ifindex', 'upstream_ofdma_ifindex',
                'upstream_ifindex', 'md_if_index', 'upstream_channel_id',
            ];
            const channelFields = [
                'ofdm_channels', 'downstream_ofdm_channels', 'ofdm',
                'ofdma_channels', 'upstream_ofdma_channels', 'ofdma',
            ];
            const countFields = [
                'ofdm_count', 'ofdm_channel_count', 'downstream_ofdm_count',
                'ofdma_count', 'ofdma_channel_count', 'upstream_ofdma_count',
            ];
            const savedEvidence = {};
            for (const key of indexFields) {
                if (this.isPositiveIndex(before[key]) && !this.isPositiveIndex(source[key])) savedEvidence[key] = before[key];
            }
            for (const key of channelFields) {
                if (this.hasPositiveChannels(before[key]) && !this.hasPositiveChannels(source[key])) savedEvidence[key] = before[key];
            }
            if (this.hasPositiveChannels(before.downstream?.ofdm) && !this.hasPositiveChannels(source.downstream?.ofdm)) {
                savedEvidence.downstream = before.downstream;
            }
            if (this.hasPositiveChannels(before.upstream?.ofdma) && !this.hasPositiveChannels(source.upstream?.ofdma)) {
                savedEvidence.upstream = before.upstream;
            }
            for (const key of countFields) {
                if (this.isPositiveIndex(before[key]) && !this.isPositiveIndex(source[key])) savedEvidence[key] = before[key];
            }
            for (const key of ['upstream_interface', 'ofdma_interface', 'interface_name']) {
                const beforeName = String(before[key] || '');
                const incomingName = String(source[key] || '');
                if (beforeName.toLowerCase().includes('ofdma') && !incomingName.toLowerCase().includes('ofdma')) {
                    savedEvidence[key] = before[key];
                }
            }

            const bestDocsis = this.docsisVersionRank(before.docsis_version) >= this.docsisVersionRank(source.docsis_version)
                ? before.docsis_version
                : source.docsis_version;
            Object.assign(target, source, saved, savedEvidence);

            const ofdmaPositive = this.hasPositiveOfdmaEvidence(before) ||
                this.hasPositiveOfdmaEvidence(source) || this.hasPositiveOfdmaEvidence(target);
            const ofdmPositive = this.hasPositiveOfdmEvidence(before) ||
                this.hasPositiveOfdmEvidence(source) || this.hasPositiveOfdmEvidence(target);
            target.ofdma_enabled = ofdmaPositive
                ? true
                : this.mergeCapabilityFlag(before.ofdma_enabled, source.ofdma_enabled);
            target.ofdm_enabled = ofdmPositive
                ? true
                : this.mergeCapabilityFlag(before.ofdm_enabled, source.ofdm_enabled);

            // Resolve DOCSIS only after effective true-dominant evidence exists.
            target.docsis_version = this.resolveDocsisVersion(
                { ...target, docsis_version: bestDocsis },
                bestDocsis || 'Unknown',
            );
            return target;
        },

        _normalizeFnSelectedMacsToCurrentRows() {
            const selected = Array.isArray(this.fnScanSelectedModemMacs) ? this.fnScanSelectedModemMacs : [];
            if (!selected.length) return;
            const wanted = new Set(selected.map(m => this.normalizeMacForMatch(m)).filter(Boolean));
            if (!wanted.size) return;

            const resolved = [];
            const resolvedNorm = new Set();
            for (const m of (this.modems || [])) {
                const norm = this.normalizeMacForMatch(m?.mac_address || '');
                if (norm && wanted.has(norm)) {
                    resolved.push(m.mac_address);
                    resolvedNorm.add(norm);
                }
            }
            if (resolved.length) {
                // Keep unresolved entries instead of dropping them, so a refresh
                // that temporarily omits rows does not silently shrink selection.
                const unresolved = selected.filter(mac => !resolvedNorm.has(this.normalizeMacForMatch(mac)));
                this.fnScanSelectedModemMacs = [...new Set([...resolved, ...unresolved])];
            }
        },

        _toIfindex(...values) {
            for (const v of values) {
                if (v === null || v === undefined || v === '') continue;
                const n = parseInt(String(v), 10);
                if (Number.isFinite(n) && n > 0) return n;
            }
            return null;
        },

        _fnTrace(step, payload = {}) {
            try {
                console.log(`[FNTRACE] ${step}`, JSON.parse(JSON.stringify(payload)));
            } catch (_) {
                console.log(`[FNTRACE] ${step}`, payload);
            }
        },

        _isMissingVendorFirmware(modem) {
            const firmware = modem?.software_version || modem?.firmware;
            // Either missing field needs identity enrichment; requiring both to
            // be absent left vendor-only and firmware-only gaps untouched.
            return this._isIdentityPlaceholder(modem?.vendor) || this._isIdentityPlaceholder(firmware);
        },

        _isMissingSelectedMetadata(modem) {
            const cableMacMissing = !String(modem?.cable_mac || '').trim();
            return this._isMissingVendorFirmware(modem) || cableMacMissing;
        },

        _shouldRefreshCacheForMetadata(modems) {
            const rows = Array.isArray(modems) ? modems : [];
            if (rows.length < 30) return { refresh: false, ratio: 0 };
            let missing = 0;
            for (const m of rows) {
                if (this._isMissingVendorFirmware(m)) missing += 1;
            }
            const ratio = rows.length ? (missing / rows.length) : 0;
            return {
                refresh: ratio >= 0.60,
                ratio,
            };
        },

        async _clearSelectedCmtsCacheSilently() {
            if (!this.selectedCmts) return false;
            try {
                const response = await fetch(`${API_BASE}/cmts/${encodeURIComponent(this.selectedCmts)}/cache/clear`, { method: 'POST' });
                const data = await response.json();
                return data?.status === 'success';
            } catch (_) {
                return false;
            }
        },

        queueSelectedModemEnrichment(rows, options = {}) {
            if (!this.enrichModems || !this.hasCmAgent) return 0;
            const maxBatch = Math.max(1, Math.min(Number(options.maxBatch || 20), 20));
            const scope = options.scope || 'selected modems';
            const fallbackCmts = options.cmts || this.selectedCmts || this.fnScanCmtsIp || '';
            if (!Array.isArray(this._targetedEnrichmentQueue)) this._targetedEnrichmentQueue = [];
            if (!(this._targetedEnrichmentKnown instanceof Set)) this._targetedEnrichmentKnown = new Set();

            let added = 0;
            for (const modem of (Array.isArray(rows) ? rows : [])) {
                if (added >= maxBatch || !this._isMissingSelectedMetadata(modem)) continue;
                const rawMac = modem?.mac_address || modem?.cm_mac_address || modem?.mac || '';
                const normalizedMac = this.normalizeMacForMatch(rawMac);
                if (!normalizedMac || this._targetedEnrichmentKnown.has(normalizedMac)) continue;
                const cmts = modem?.cmts || modem?.cmts_hostname || modem?.cmts_ip || fallbackCmts;
                if (!cmts) continue;
                this._targetedEnrichmentKnown.add(normalizedMac);
                this._targetedEnrichmentQueue.push({
                    mac: this.normalizeMacForDisplay(rawMac),
                    normalizedMac,
                    cmts,
                });
                added += 1;
            }
            if (!added) return 0;

            if (!this.targetedEnrichmentRunning) {
                this.targetedEnrichmentProgress = {
                    current: 0,
                    total: added,
                    failed: 0,
                    unresolved: 0,
                    scope,
                    action: 'Queueing selected modems…',
                    status: 'running',
                };
                this._runTargetedEnrichmentQueue().catch(error => {
                    console.warn('Targeted enrichment failed:', error?.message || error);
                });
            } else {
                this.targetedEnrichmentProgress = {
                    ...this.targetedEnrichmentProgress,
                    total: Number(this.targetedEnrichmentProgress.total || 0) + added,
                    scope: this.targetedEnrichmentProgress.scope === scope ? scope : 'selected modems',
                };
            }
            return added;
        },

        async _runTargetedEnrichmentQueue() {
            if (this.targetedEnrichmentRunning) return;
            this.targetedEnrichmentRunning = true;
            const worker = async () => {
                while (this._targetedEnrichmentQueue?.length) {
                    const target = this._targetedEnrichmentQueue.shift();
                    this.targetedEnrichmentProgress = {
                        ...this.targetedEnrichmentProgress,
                        action: `Reading modem metadata for ${target.mac}…`,
                    };
                    const outcome = await this._refreshTargetedModemIdentity(target);
                    this.targetedEnrichmentProgress = {
                        ...this.targetedEnrichmentProgress,
                        current: Number(this.targetedEnrichmentProgress.current || 0) + 1,
                        failed: Number(this.targetedEnrichmentProgress.failed || 0) + (outcome === 'failed' ? 1 : 0),
                        unresolved: Number(this.targetedEnrichmentProgress.unresolved || 0) + (outcome === 'unresolved' ? 1 : 0),
                    };
                }
            };

            await Promise.all([worker(), worker()]);
            this.targetedEnrichmentRunning = false;
            const issues = Number(this.targetedEnrichmentProgress.failed || 0) + Number(this.targetedEnrichmentProgress.unresolved || 0);
            this.targetedEnrichmentProgress = {
                ...this.targetedEnrichmentProgress,
                action: issues ? `Completed with ${issues} unresolved modem(s)` : 'Selected modem enrichment complete',
                status: issues ? 'warning' : 'completed',
            };
            this._targetedEnrichmentKnown?.clear();

            const completedTotal = this.targetedEnrichmentProgress.total;
            setTimeout(() => {
                if (!this.targetedEnrichmentRunning && this.targetedEnrichmentProgress.total === completedTotal) {
                    this.targetedEnrichmentProgress = {
                        current: 0, total: 0, failed: 0, unresolved: 0,
                        scope: '', action: '', status: 'idle',
                    };
                }
            }, 10000);
        },

        async _refreshTargetedModemIdentity(target) {
            try {
                const response = await fetch(`${API_BASE}/modems/${encodeURIComponent(target.mac)}/refresh`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ cmts: target.cmts }),
                });
                const queued = await response.json();
                if (!response.ok || queued?.status !== 'success' || !queued?.request_id) return 'failed';
                const requestId = Number(queued.request_id);
                const terminalStates = new Set(['completed', 'failed', 'timed_out', 'cancelled']);

                for (let attempt = 0; attempt < 180; attempt++) {
                    await new Promise(resolve => setTimeout(resolve, 2000));
                    const statusResponse = await fetch(`${API_BASE}/modems/${encodeURIComponent(target.mac)}/refresh/status`);
                    const statusData = await statusResponse.json();
                    const refresh = statusData?.refresh || statusData?.request;
                    if (!statusResponse.ok || !refresh) continue;
                    if (refresh.id && Number(refresh.id) !== requestId) continue;
                    const status = String(refresh.status || '').toLowerCase();
                    if (!terminalStates.has(status)) continue;
                    if (status !== 'completed') return 'failed';

                    const modemResponse = await fetch(`${API_BASE}/modems/${encodeURIComponent(target.mac)}`);
                    const modemData = await modemResponse.json();
                    if (!modemResponse.ok || modemData?.status !== 'success' || !modemData.modem) return 'unresolved';
                    const updated = modemData.modem;
                    let mergedTarget = updated;
                    for (const modem of (this.modems || [])) {
                        if (this.normalizeMacForMatch(modem?.mac_address) !== target.normalizedMac) continue;
                        this._mergeModemPreservingCmts(modem, updated);
                        mergedTarget = modem;
                    }
                    if (this.selectedModem && this.normalizeMacForMatch(this.selectedModem.mac_address) === target.normalizedMac) {
                        this._mergeModemPreservingCmts(this.selectedModem, updated);
                        mergedTarget = this.selectedModem;
                    }
                    this.modems = this.modems.slice();
                    return this._isMissingSelectedMetadata(mergedTarget) ? 'unresolved' : 'completed';
                }
            } catch (error) {
                console.warn(`Targeted enrichment failed for ${target.mac}:`, error?.message || error);
            }
            return 'failed';
        },

        async _requestDeltaEnrichmentForSelectedCmts() {
            if (!this.selectedCmts || !this.enrichModems) return;
            try {
                const response = await fetch(`${API_BASE}/cmts/${encodeURIComponent(this.selectedCmts)}/enrich/delta`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ max_batch: 25 }),
                });
                const data = await response.json();
                if (data?.status === 'success' && Number(data?.enqueued || 0) > 0) {
                    this.$toast?.info(`Delta enrichment queued for ${data.enqueued} modem(s).`);
                }
            } catch (error) {
                console.warn('Delta enrichment request failed:', error?.message || error);
            }
        },

        async _discoverPreferredOFDMAIfindex(macAddress, cmtsIp) {
            if (!macAddress || !cmtsIp) return null;
            try {
                // 1) Most authoritative: dedicated modem OFDMA discovery.
                const discoverResp = await fetch(`${API_BASE}/pypnm/cmts/ofdma/discover/${encodeURIComponent(macAddress)}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ cmts_ip: cmtsIp, community: this.fnScanCommunity || this.snmpCommunity }),
                });
                if (discoverResp.ok) {
                    const discover = await discoverResp.json();
                    const discoveredIf = this._toIfindex(
                        discover?.ofdma_ifindex,
                        discover?.ifindex,
                        discover?.data?.ofdma_ifindex,
                    );
                    if (discoveredIf) return discoveredIf;
                }

                // 2) Fallback: upstream/interfaces endpoint, OFDMA-only.
                const response = await fetch(`${API_BASE}/pypnm/upstream/interfaces/${encodeURIComponent(macAddress)}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ cmts_ip: cmtsIp, community: this.fnScanCommunity || this.snmpCommunity }),
                });
                if (!response.ok) return null;
                const result = await response.json();
                if (!result?.success) return null;

                const firstOfdma = Array.isArray(result.ofdma_channels) && result.ofdma_channels.length
                    ? result.ofdma_channels[0]
                    : null;
                return this._toIfindex(
                    firstOfdma?.ifindex,
                    firstOfdma?.ofdma_ifindex,
                );
            } catch (_) {
                return null;
            }
        },

        _deriveTopologyLevels(nodeLike) {
            const raw = String(nodeLike || '').trim();
            if (!raw || !raw.includes('.')) return {};

            const parts = raw.split('.').filter(Boolean);
            if (parts.length < 2) return {};

            const out = {
                topology_node_id: parts.slice(0, 2).join('.'),
                topology_group_amplifier: null,
                topology_end_amplifier: null,
                topology_tap: null,
            };

            // Token chain convention (example):
            // ZTM-LC0002.ZTM-0063-03.G05.E06.MB.T3
            // Node = first 2 parts
            // Group Amp = through Gxx token
            // End Amp = through Exx token
            // Tap = through Tx token
            const gIdx = parts.findIndex(p => /^G\d+$/i.test(String(p || '').trim()));
            const eIdx = parts.findIndex(p => /^E\d+$/i.test(String(p || '').trim()));
            const tIdx = parts.findIndex(p => /^T\d+$/i.test(String(p || '').trim()));
            if (gIdx >= 0) out.topology_group_amplifier = parts.slice(0, gIdx + 1).join('.');
            if (eIdx >= 0) out.topology_end_amplifier = parts.slice(0, eIdx + 1).join('.');
            if (tIdx >= 0) out.topology_tap = parts.slice(0, tIdx + 1).join('.');

            // Customer chain convention (example):
            // AD00.0000010X.001.001.01.01 -> Tap
            // AD00.0000010X.001.001.01    -> End Amp
            // AD00.0000010X.001.001       -> Group Amp
            // AD00.0000010X               -> Node
            if (!out.topology_group_amplifier && parts.length >= 4) out.topology_group_amplifier = parts.slice(0, 4).join('.');
            if (!out.topology_end_amplifier && parts.length >= 5) out.topology_end_amplifier = parts.slice(0, 5).join('.');
            if (!out.topology_tap && parts.length >= 6) out.topology_tap = parts.slice(0, 6).join('.');

            return out;
        },

        async _enrichFnSelectorTopologyMetadata() {
            const dottedNode = String(this.fnScanFiberNode || '').trim();
            const bridgeNode = String(this.fnScanTopologyBridgeNodeId || '').trim();
            const fallbackNode = dottedNode.includes('.') ? dottedNode : (bridgeNode.includes('.') ? bridgeNode : '');
            // Scope to selected CMTS — this.modems can contain cross-network
            // search results; sending every area's nodes is wrong and expensive.
            const cmtsScope = (this.fnScanCmtsIp || '').trim();
            const nodeIds = [...new Set((this.modems || [])
                .filter(m => !cmtsScope || !m.cmts_ip || m.cmts_ip === cmtsScope)
                .map(m => (m?.fiber_node || '').trim())
                .filter(v => v && v.includes('.')))];
            if (!nodeIds.length && fallbackNode) {
                nodeIds.push(fallbackNode);
            }
            try {
                let metaMap = {};
                if (nodeIds.length) {
                    const response = await fetch(`${API_BASE}/topology/node-meta?node_ids=${encodeURIComponent(nodeIds.join(','))}&direction=US`);
                    const data = await response.json();
                    if (data?.status === 'success' && data?.node_meta) {
                        metaMap = data.node_meta || {};
                    }
                }
                this.modems = (this.modems || []).map(m => {
                    const derived = this._deriveTopologyLevels(m.linked_node_id || m.fiber_node || '');
                    const lookupNode = (derived.topology_node_id || (String(m.fiber_node || '').includes('.') ? m.fiber_node : '') || fallbackNode || '').trim();
                    const meta = metaMap[lookupNode] || null;
                    const metaGroup = meta?.serving_group || meta?.group || '';
                    const metaEnd = meta?.end_amplifier || meta?.end_amp || meta?.amp || meta?.end || meta?.cmts || '';
                    const metaTap = meta?.tap || meta?.tap_name || meta?.tap_id || '';
                    return {
                        ...m,
                        topology_node_id: derived.topology_node_id || m.topology_node_id || lookupNode || '',
                        topology_group_amplifier: derived.topology_group_amplifier || metaGroup || m.topology_group_amplifier || '',
                        topology_end_amplifier: derived.topology_end_amplifier || metaEnd || m.topology_end_amplifier || '',
                        topology_tap: derived.topology_tap || metaTap || m.topology_tap || '',
                        topology_segment: (meta?.segment) || m.topology_segment || '',
                        topology_serving_group: (meta?.serving_group) || m.topology_serving_group || '',
                    };
                });

                // FNxx discovery labels do not match topology node IDs. Bridge via
                // serving-group pattern: <CMTS>-G### (e.g., FN37 -> ...-G037).
                const cmtsCandidates = [...new Set([
                    String(this.fnScanCmts?.name || '').trim(),
                    String(this.fnScanCmts?.hostname || '').trim(),
                    String(this.fnScanCmts?.cmts || '').trim(),
                ].filter(Boolean))];
                // Only look up the serving group for the selected FN, not
                // every FN on the CMTS. Other FNs are irrelevant here.
                const selFnForSg = String(this.fnScanFiberNode || '').trim().toUpperCase();
                const sgSet = new Set();
                if (selFnForSg && cmtsCandidates.length) {
                    const mFn = /^FN(\d{1,3})$/.exec(selFnForSg);
                    if (mFn) {
                        const gnum = String(parseInt(mFn[1], 10)).padStart(3, '0');
                        for (const cmtsName of cmtsCandidates) {
                            sgSet.add(`${cmtsName}-G${gnum}`);
                        }
                    }
                }
                const groups = [...sgSet];
                if (groups.length) {
                    const sgResp = await fetch(`${API_BASE}/topology/serving-group-meta?groups=${encodeURIComponent(groups.join(','))}&direction=US`);
                    const sgData = await sgResp.json();
                    const sgMeta = (sgData?.status === 'success' && sgData?.serving_group_meta) ? sgData.serving_group_meta : {};
                    this.modems = (this.modems || []).map(m => {
                        if (m.topology_group_amplifier || m.topology_end_amplifier) return m;
                        const fn = String(m.fiber_node || '').trim().toUpperCase();
                        const mFn = /^FN(\d{1,3})$/.exec(fn);
                        if (!mFn) return m;
                        const gnum = String(parseInt(mFn[1], 10)).padStart(3, '0');
                        const exact = cmtsCandidates
                            .map(c => ({ key: `${c}-G${gnum}`, meta: sgMeta[`${c}-G${gnum}`] }))
                            .find(x => !!x.meta);
                        const picked = exact || null;
                        if (!picked?.meta) return m;
                        const sgGroup = picked.meta.serving_group || picked.key || '';
                        const sgEnd = picked.meta.end_amplifier || picked.meta.end_amp || picked.meta.amp || picked.meta.end || picked.meta.cmts || '';
                        const sgTap = picked.meta.tap || picked.meta.tap_name || picked.meta.tap_id || '';
                        return {
                            ...m,
                            topology_group_amplifier: sgGroup || m.topology_group_amplifier || '',
                            topology_end_amplifier: sgEnd || m.topology_end_amplifier || '',
                            topology_tap: sgTap || m.topology_tap || '',
                            topology_segment: picked.meta.segment || m.topology_segment || '',
                            topology_node_id: picked.meta.node_id || m.topology_node_id || '',
                        };
                    });
                }

                // ── Serving-group mismatch detection ───────────────────────
                // Only collect topology_node_id from modems matching the selected
                // FN. Looking up every node on the CMTS is wasteful and pulls in
                // unrelated areas (AK00, RT18, etc. that share the same CMTS).
                const selFnMismatch = String(this.fnScanFiberNode || '').trim().toUpperCase();
                const allNodeIds = [...new Set((this.modems || [])
                    .filter(m => {
                        if (!selFnMismatch) return true;
                        const mFn = String(m.fiber_node || '').trim().toUpperCase();
                        return mFn === selFnMismatch;
                    })
                    .map(m => (m.topology_node_id || '').trim())
                    .filter(v => v && v.includes('.')))];
                if (allNodeIds.length > 0) {
                    const nmResp = await fetch(`${API_BASE}/topology/node-meta?node_ids=${encodeURIComponent(allNodeIds.join(','))}&direction=US`);
                    const nmData = await nmResp.json();
                    const nmMeta = (nmData?.status === 'success' && nmData?.node_meta) ? nmData.node_meta : {};

                    // Determine expected serving_group(s) from node-meta of modems
                    // that belong to the selected FN. DAA/RPHY topologies can have
                    // multiple serving groups per FN (one per DAA), so collect all.
                    const selFn = String(this.fnScanFiberNode || '').trim().toUpperCase();
                    const expectedSgs = new Set();
                    for (const m of (this.modems || [])) {
                        const mFn = String(m.fiber_node || '').trim().toUpperCase();
                        if (mFn !== selFn) continue;
                        const nid = (m.topology_node_id || '').trim();
                        const sg = (nmMeta[nid]?.serving_group || '').trim();
                        if (sg) expectedSgs.add(sg);
                    }

                    if (expectedSgs.size > 0) {
                        this.fnScanExpectedServingGroup = [...expectedSgs].join(', ');
                        this.modems = (this.modems || []).map(m => {
                            const nid = (m.topology_node_id || '').trim();
                            const sg = (nmMeta[nid]?.serving_group || '').trim();
                            const mismatch = !!(sg && !expectedSgs.has(sg));
                            return {
                                ...m,
                                topology_serving_group: sg || m.topology_serving_group || '',
                                _linked_node_mismatch: mismatch,
                            };
                        });
                    }
                }
            } catch (_) {
                // Best-effort topology context only.
            }
        },

        _mergeSearchSeed(modems) {
            if (!Array.isArray(modems) || !modems.length) return;
            const macSet = new Set(this.searchSeedMacs || []);
            const ipSet = new Set(this.searchSeedIps || []);
            const fnSet = new Set(this.searchSeedFiberNodes || []);
            for (const m of modems) {
                const mac = (m?.mac_address || '').trim();
                const ip = (m?.ip_address || '').trim();
                const fn = (m?.fiber_node || '').trim();
                if (mac) macSet.add(mac);
                if (ip) ipSet.add(ip);
                if (fn) fnSet.add(fn);
            }
            this.searchSeedMacs = Array.from(macSet).sort();
            this.searchSeedIps = Array.from(ipSet).sort();
            this.searchSeedFiberNodes = Array.from(fnSet).sort();
        },

        async preloadSearchSeed() {
            try {
                const response = await fetch(`${API_BASE}/modems?limit=5000`);
                const data = await response.json();
                if (data?.status === 'success' && Array.isArray(data.modems)) {
                    this._mergeSearchSeed(data.modems);
                }
            } catch (_) {
                // Suggestions are best-effort only.
            }
        },

        async onSearchInput() {
            this.showSearchSuggestions = true;
            if (this.searchType === 'cpe_ip') {
                if (this._cpeSuggestTimer) clearTimeout(this._cpeSuggestTimer);
                const q = (this.searchValue || '').trim();
                if (!q) {
                    this.cpeSearchSuggestions = [];
                    return;
                }
                this._cpeSuggestTimer = setTimeout(async () => {
                    try {
                        const params = new URLSearchParams({ q, limit: '10' });
                        const response = await fetch(`${API_BASE}/modems/cpe-suggestions?${params.toString()}`);
                        const data = await response.json();
                        this.cpeSearchSuggestions = data?.status === 'success' && Array.isArray(data.suggestions)
                            ? data.suggestions : [];
                    } catch (_) {
                        this.cpeSearchSuggestions = [];
                    }
                }, 250);
                return;
            }
            if (!this.useTopologySearch) return;

            // Only fetch topology suggestions for topology-specific search types;
            // never auto-switch the user's chosen type (mac, ip, name, fiber_node).
            if (!['fibernode', 'postal_house', 'customer_id'].includes(this.searchType)) {
                return;
            }

            let q = (this.searchValue || '').trim();
            if (this.searchType === 'customer_id' && q && !q.match(/^(RES|B2B)-/i)) {
                q = this.customerIdPrefix + q;
            }
            if (q.length < 2) {
                this.topologySuggestions = [];
                return;
            }

            try {
                const params = new URLSearchParams({
                    type: this.searchType,
                    q,
                    limit: '10',
                });
                const response = await fetch(`${API_BASE}/topology/search/suggest?${params.toString()}`);
                const data = await response.json();
                if (data?.status === 'success' && Array.isArray(data.suggestions)) {
                    this.topologySuggestions = data.suggestions;
                } else {
                    this.topologySuggestions = [];
                }
            } catch (_) {
                this.topologySuggestions = [];
            }
        },

        hideSearchSuggestionsSoon() {
            setTimeout(() => {
                this.showSearchSuggestions = false;
            }, 120);
        },

        applySearchSuggestion(value) {
            const v = String(value || '');
            if (this.useTopologySearch && this.searchType === 'postal_house') {
                const parts = v.trim().split(/\s+/);
                this.searchValue = parts[0] || '';
                this.searchHouseNumber = parts.slice(1).join(' ') || '';
            } else if (this.useTopologySearch && this.searchType === 'customer_id') {
                const match = v.match(/^(RES|B2B)-(.*)/i);
                if (match) {
                    this.customerIdPrefix = match[1].toUpperCase() + '-';
                    this.searchValue = match[2];
                } else {
                    this.searchValue = v;
                }
            } else if (this.searchType === 'mac') {
                this.searchValue = this.formatMacForSearchStyle(v, this.searchValue);
            } else {
                this.searchValue = v;
            }
            this.showSearchSuggestions = false;
        },

        useLogoFallback(event) {
            const img = event && event.target ? event.target : null;
            if (!img) return;

            // Avoid a loop if the fallback image also fails.
            if (img.dataset.fallbackApplied === '1') {
                img.style.display = 'none';
                return;
            }

            img.dataset.fallbackApplied = '1';
            const basePath = window.BASE_PATH || '';
            img.src = `${basePath}/static/images/logo-fallback.png`;
        },

        hasKnownDocsisVersion(version) {
            return this.docsisVersionRank(version) > 0;
        },

        docsisVersionRank(version) {
            const value = (version || '').toString().trim().toLowerCase();
            if (value.includes('4.0')) return 40;
            if (value.includes('3.1')) return 31;
            if (value.includes('3.0')) return 30;
            if (value.includes('2.0')) return 20;
            if (value.includes('1.1')) return 11;
            if (value.includes('1.0')) return 10;
            return 0;
        },

        isOnlineModem(modem) {
            const status = String(modem?.status || '').trim().toLowerCase();
            const statusCode = Number(modem?.status_code ?? modem?.statusCode ?? NaN);
            return ['operational', 'online', 'registrationcomplete', 'ipcomplete'].includes(status) ||
                   statusCode === 6 || statusCode === 8;
        },

        isPositiveCapability(value) {
            if (value === true) return true;
            if (typeof value === 'number') return Number.isFinite(value) && value > 0;
            return ['true', 'yes', 'on', 'active', 'available'].includes(String(value || '').trim().toLowerCase());
        },

        isPositiveIndex(value) {
            const parsed = Number(value);
            return Number.isFinite(parsed) && parsed > 0;
        },

        hasPositiveChannels(value) {
            if (Array.isArray(value)) return value.length > 0;
            if (!value || typeof value !== 'object') return false;
            if (this.isPositiveIndex(value.count)) return true;
            return ['channels', 'entries', 'results'].some(key =>
                Array.isArray(value[key]) && value[key].length > 0
            );
        },

        hasPositiveOfdmaEvidence(modem) {
            if (!modem) return false;
            const indexes = [
                modem.ofdma_ifindex,
                modem.ofdma_rf_port_ifindex,
                modem.upstream_ofdma_ifindex,
            ];
            const interfaces = [
                modem.upstream_interface,
                modem.ofdma_interface,
                modem.interface_name,
            ];
            const counts = [
                modem.ofdma_count,
                modem.ofdma_channel_count,
                modem.upstream_ofdma_count,
            ];
            const channels = [
                modem.ofdma_channels,
                modem.ofdma,
                modem.upstream_ofdma_channels,
                modem.upstream?.ofdma,
            ];
            return this.isPositiveCapability(modem.ofdma_enabled) ||
                   indexes.some(value => this.isPositiveIndex(value)) ||
                   interfaces.some(value => String(value || '').toLowerCase().includes('ofdma')) ||
                   counts.some(value => this.isPositiveIndex(value)) ||
                   channels.some(value => this.hasPositiveChannels(value));
        },

        hasPositiveOfdmEvidence(modem) {
            if (!modem) return false;
            const indexes = [
                modem.ofdm_ifindex,
                modem.ofdm_rf_port_ifindex,
                modem.downstream_ofdm_ifindex,
            ];
            const counts = [
                modem.ofdm_count,
                modem.ofdm_channel_count,
                modem.downstream_ofdm_count,
            ];
            const channels = [
                modem.ofdm_channels,
                modem.ofdm,
                modem.downstream_ofdm_channels,
                modem.downstream?.ofdm,
            ];
            return this.isPositiveCapability(modem.ofdm_enabled) ||
                   indexes.some(value => this.isPositiveIndex(value)) ||
                   counts.some(value => this.isPositiveIndex(value)) ||
                   channels.some(value => this.hasPositiveChannels(value));
        },

        mergeCapabilityFlag(...values) {
            if (values.some(value => this.isPositiveCapability(value))) return true;
            if (values.every(value => value == null)) return null;
            return false;
        },

        capabilityStatus(modem, direction) {
            const status = String(modem?.status || '').trim().toLowerCase();
            if (status === 'offline' || status === 'other') return 'red';
            if (this.isDirectionalPartialService(modem, direction)) return 'orange';
            const positive = direction === 'downstream'
                ? this.hasPositiveOfdmEvidence(modem)
                : this.hasPositiveOfdmaEvidence(modem);
            if (positive) return 'green';
            if (this.isOnlineModem(modem)) return 'gray';
            return 'red';
        },

        resolveDocsisVersion(modem, fallback = 'Unknown') {
            let rank = this.docsisVersionRank(modem?.docsis_version);
            if (this.hasPositiveOfdmEvidence(modem) || this.hasPositiveOfdmaEvidence(modem)) {
                rank = Math.max(rank, 31);
            } else if (rank === 0 && this.isOnlineModem(modem)) {
                rank = 30;
            }

            const labels = {
                10: 'DOCSIS 1.0', 11: 'DOCSIS 1.1', 20: 'DOCSIS 2.0',
                30: 'DOCSIS 3.0', 31: 'DOCSIS 3.1', 40: 'DOCSIS 4.0',
            };
            return labels[rank] || fallback;
        },

        fnVendorShortLabel(vendor) {
            const raw = String(vendor || '').trim();
            if (!raw) return '—';
            if (/compal/i.test(raw)) return 'Compal';
            return raw;
        },

        fnDocsisShortLabel(version) {
            const raw = (version || '').toString().trim();
            if (!this.hasKnownDocsisVersion(raw)) return '';
            if (raw.includes('4.0')) return '4.0';
            if (raw.includes('3.1')) return '3.1';
            if (raw.includes('3.0')) return '3.0';
            return raw;
        },

        fnSelectorDocsisValue(modem) {
            return this.fnDocsisShortLabel(this.resolveDocsisVersion(modem, 'Unknown')) || 'Unknown';
        },

        fnSelectorVendorValue(modem) {
            const label = this.fnVendorShortLabel(modem?.vendor);
            return label === '—' || this._isIdentityPlaceholder(label) ? 'Unknown' : label;
        },

        fnSelectorTypeValue(modem) {
            const model = String(modem?.model || '').trim();
            return this._isIdentityPlaceholder(model) ? 'Unknown' : model;
        },

        clearFnScanSelectorFilters() {
            this.fnScanSelectorFilterFn = '';
            this.fnScanSelectorFilterCableMac = '';
            this.fnScanSelectorFilterGroupAmp = '';
            this.fnScanSelectorFilterEndAmp = '';
            this.fnScanSelectorFilterTap = '';
            this.fnScanSelectorFilterDocsis = '';
            this.fnScanSelectorFilterVendor = '';
            this.fnScanSelectorFilterType = '';
            this.fnScanSelectorFilterImpairment = '';
            this.fnScanModemSearch = '';
        },

        formatTopologyGroupAmplifier(value) {
            const parts = String(value || '').trim().split('.').filter(Boolean);
            const token = parts.find(p => /^G\d+$/i.test(String(p || '').trim()));
            if (token) return token.toUpperCase();
            if (parts.length >= 3 && /^\d+$/.test(parts[2])) return parts[2];
            return '';
        },

        formatTopologyEndAmplifier(value) {
            const parts = String(value || '').trim().split('.').filter(Boolean);
            const token = parts.find(p => /^E\d+$/i.test(String(p || '').trim()));
            if (token) return token.toUpperCase();
            if (parts.length >= 4 && /^\d+$/.test(parts[3])) return String(parseInt(parts[3], 10));
            return '';
        },

        formatTopologyTap(value) {
            const parts = String(value || '').trim().split('.').filter(Boolean);
            const token = parts.find(p => /^T\d+$/i.test(String(p || '').trim()));
            if (token) return token.toUpperCase();
            if (parts.length >= 6 && /^\d+$/.test(parts[4]) && /^\d+$/.test(parts[5])) return `${parts[4].padStart(2, '0')}.${parts[5].padStart(2, '0')}`;
            return '';
        },

        modemCoordinates(modem) {
            const rawLat = modem?.lat;
            const rawLon = modem?.lon;
            if (rawLat === null || rawLat === undefined || rawLat === '' ||
                rawLon === null || rawLon === undefined || rawLon === '') return null;
            const lat = Number(rawLat);
            const lon = Number(rawLon);
            if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
            if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
            return { lat, lon };
        },

        hasModemCoordinates(modem) {
            return this.modemCoordinates(modem) !== null;
        },

        openModemMap(modem) {
            const coordinates = this.modemCoordinates(modem);
            if (!coordinates) {
                this.$toast?.warning('No valid latitude/longitude is available for this modem');
                return;
            }
            const { lat, lon } = coordinates;
            const url = `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=18/${lat}/${lon}`;
            const mapWindow = window.open(url, '_blank', 'noopener,noreferrer');
            if (mapWindow) mapWindow.opener = null;
        },

        _applyFnScanProgress(progress) {
            if (!progress?.found) return;
            const incoming = Number(progress.pct || 0);
            const current = Number(this.fnScanProgress?.pct || 0);
            const safeIncoming = Number.isFinite(incoming) ? Math.min(100, Math.max(0, incoming)) : current;
            this.fnScanProgress = {
                ...this.fnScanProgress,
                ...progress,
                pct: Math.max(current, safeIncoming),
            };
        },

        _destroyFnSelectedMap() {
            if (this._fnSelectedMapRenderTimer) {
                clearTimeout(this._fnSelectedMapRenderTimer);
                this._fnSelectedMapRenderTimer = null;
            }
            if (this._fnSelectedMapRequestController) {
                this._fnSelectedMapRequestController.abort();
                this._fnSelectedMapRequestController = null;
            }
            this._fnSelectedMapRenderGeneration = (this._fnSelectedMapRenderGeneration || 0) + 1;
            if (this._fnSelectedMapInstance) {
                try { this._fnSelectedMapInstance.remove(); } catch (_) {}
                this._fnSelectedMapInstance = null;
            }
            this.fnSelectedMapPathStatus = {
                ...this.fnSelectedMapPathStatus,
                loading: false,
            };
        },

        _scheduleFnSelectedMapRender() {
            if (!this.fnSelectedMapVisible) return;
            if (this._fnSelectedMapRenderTimer) clearTimeout(this._fnSelectedMapRenderTimer);
            this._fnSelectedMapRenderTimer = setTimeout(() => {
                this._fnSelectedMapRenderTimer = null;
                this.renderFnSelectedMap();
            }, 80);
        },

        toggleFnSelectedMap() {
            this.fnSelectedMapVisible = !this.fnSelectedMapVisible;
            if (!this.fnSelectedMapVisible) {
                this._destroyFnSelectedMap();
                return;
            }
            this.$nextTick(() => this._scheduleFnSelectedMapRender());
        },

        _fnMapCoordinates(latValue, lonValue) {
            const lat = Number(latValue);
            const lon = Number(lonValue);
            if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
            if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
            if (lat === 0 && lon === 0) return null;
            return { lat, lon };
        },

        feetToMeters(value) {
            if (value === null || value === undefined || value === '') return null;
            const feet = Number(value);
            return Number.isFinite(feet) ? feet * 0.3048 : null;
        },

        _fnImpulseEchoesForMac(macAddress) {
            const target = this.normalizeMacForMatch(macAddress);
            if (!target) return [];
            const modem = (this.fnImpulseResult?.modems || []).find(
                item => this.normalizeMacForMatch(item?.mac_address) === target
            );
            const echoes = [];
            for (const result of (modem?.results || [])) {
                const report = result?.analysis?.echo?.report || {};
                for (const echo of (report.echoes || [])) {
                    const distanceFt = Number(echo?.distance_ft);
                    const reportedDistanceM = Number(echo?.distance_m);
                    const distanceM = Number.isFinite(reportedDistanceM)
                        ? reportedDistanceM
                        : this.feetToMeters(distanceFt);
                    if (!Number.isFinite(distanceM)) continue;
                    echoes.push({
                        direction: result?.direction === 'upstream' ? 'US' : 'DS',
                        distanceM,
                        cableType: report?.cable_type || '',
                        velocityFactor: Number(report?.velocity_factor),
                    });
                }
            }
            return echoes.slice(0, 6);
        },

        _appendFnMapPopupLine(parent, text, className = '') {
            if (!text) return;
            const line = document.createElement('div');
            if (className) line.className = className;
            line.textContent = text;
            parent.appendChild(line);
        },

        _drawFnSelectedMap(points, pathPayload, pathError = '') {
            if (!this.fnSelectedMapVisible) return;
            const mapElement = this.$refs.fnSelectedModemMap;
            if (!mapElement || !points.length || !window.L) return;
            if (this._fnSelectedMapInstance) {
                try { this._fnSelectedMapInstance.remove(); } catch (_) {}
            }

            const map = window.L.map(mapElement, { scrollWheelZoom: true });
            this._fnSelectedMapInstance = map;
            window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 19,
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
            }).addTo(map);

            const snapshotDate = String(pathPayload?.snapshot_date || 'latest');
            const pointByMac = new Map(points.map(point => [
                this.normalizeMacForMatch(point?.mac_address),
                point,
            ]));
            const graphNodes = new Map();
            const graphEdges = new Map();
            const missingCoordinateKeys = new Set();
            let resolvedPathCount = 0;
            let unresolvedCount = 0;

            for (const point of points) {
                const bareMac = this.normalizeMacForMatch(point?.mac_address);
                if (!bareMac) continue;
                graphNodes.set(`${snapshotDate}:cm:${bareMac}`, {
                    key: `${snapshotDate}:cm:${bareMac}`,
                    role: 'modem',
                    id: point.mac_address || bareMac,
                    coordinates: point.coordinates,
                    modem: point,
                });
            }

            for (const path of (pathPayload?.paths || [])) {
                const bareMac = this.normalizeMacForMatch(path?.mac);
                const point = pointByMac.get(bareMac);
                if (!point || !path?.found) {
                    unresolvedCount += 1;
                    continue;
                }
                resolvedPathCount += 1;
                if (!path.complete) unresolvedCount += 1;
                const cmNode = graphNodes.get(`${snapshotDate}:cm:${bareMac}`);
                const roleNodes = {};
                for (const node of (path.nodes || [])) {
                    if (!['end_amp', 'group_amp', 'fiber_node'].includes(node?.role)) continue;
                    const key = `${snapshotDate}:${node.id}`;
                    const coordinates = this._fnMapCoordinates(node.lat, node.lon);
                    if (!coordinates) missingCoordinateKeys.add(key);
                    if (!graphNodes.has(key)) {
                        graphNodes.set(key, {
                            key,
                            role: node.role,
                            id: node.id,
                            coordinates,
                            node,
                        });
                    }
                    roleNodes[node.role] = graphNodes.get(key);
                }

                const ordered = [cmNode, roleNodes.end_amp, roleNodes.group_amp, roleNodes.fiber_node];
                for (let index = 0; index < ordered.length - 1; index += 1) {
                    const from = ordered[index];
                    const to = ordered[index + 1];
                    if (!from || !to || !from.coordinates || !to.coordinates) continue;
                    const edgeKey = `${from.key}->${to.key}`;
                    if (!graphEdges.has(edgeKey)) {
                        graphEdges.set(edgeKey, { key: edgeKey, from, to, modems: new Set() });
                    }
                    graphEdges.get(edgeKey).modems.add(bareMac);
                }
            }

            for (const edge of graphEdges.values()) {
                const modemSpecific = edge.from.role === 'modem';
                const line = window.L.polyline([
                    [edge.from.coordinates.lat, edge.from.coordinates.lon],
                    [edge.to.coordinates.lat, edge.to.coordinates.lon],
                ], {
                    color: modemSpecific ? '#6c757d' : '#0d6efd',
                    weight: modemSpecific ? 2 : 4,
                    opacity: 0.8,
                    dashArray: modemSpecific ? '6 5' : null,
                }).addTo(map);
                const popup = document.createElement('div');
                const title = document.createElement('strong');
                title.textContent = 'Logical topology segment';
                popup.appendChild(title);
                this._appendFnMapPopupLine(popup, `${edge.from.id} → ${edge.to.id}`);
                this._appendFnMapPopupLine(
                    popup,
                    `${edge.modems.size} selected modem${edge.modems.size === 1 ? '' : 's'} use this segment`,
                    'text-muted small'
                );
                line.bindPopup(popup);
            }

            const bounds = [];
            const roleStyles = {
                modem: { color: '#dc3545', fillColor: '#dc3545', radius: 6, label: 'Cable modem' },
                end_amp: { color: '#fd7e14', fillColor: '#fd7e14', radius: 7, label: 'End amplifier' },
                group_amp: { color: '#0d6efd', fillColor: '#0d6efd', radius: 8, label: 'Group amplifier' },
                fiber_node: { color: '#198754', fillColor: '#198754', radius: 10, label: 'Fiber Node' },
            };
            for (const graphNode of graphNodes.values()) {
                if (!graphNode.coordinates) continue;
                const style = roleStyles[graphNode.role] || roleStyles.modem;
                const marker = window.L.circleMarker(
                    [graphNode.coordinates.lat, graphNode.coordinates.lon],
                    { ...style, fillOpacity: 0.9, weight: 2 }
                ).addTo(map);
                const popup = document.createElement('div');
                const title = document.createElement('strong');
                title.textContent = `${style.label}: ${graphNode.id}`;
                popup.appendChild(title);
                if (graphNode.role === 'modem') {
                    const modem = graphNode.modem || {};
                    for (const value of [modem.ip_address, modem.fiber_node, modem.address]) {
                        this._appendFnMapPopupLine(popup, value);
                    }
                    const echoes = this._fnImpulseEchoesForMac(modem.mac_address);
                    if (echoes.length) {
                        this._appendFnMapPopupLine(popup, 'Electrical reflection distances', 'fw-semibold mt-1');
                        for (const echo of echoes) {
                            const distance = `${echo.distanceM.toFixed(1)} m`;
                            const vf = Number.isFinite(echo.velocityFactor) ? `, VF ${echo.velocityFactor.toFixed(2)}` : '';
                            this._appendFnMapPopupLine(
                                popup,
                                `${echo.direction}: ${distance}${echo.cableType ? `, ${echo.cableType}` : ''}${vf}`,
                                'small'
                            );
                        }
                        this._appendFnMapPopupLine(
                            popup,
                            'No fault pin is projected: direction and routed cable lengths are not verified.',
                            'text-warning small'
                        );
                    }
                } else {
                    this._appendFnMapPopupLine(popup, graphNode.node?.node_type || '');
                    const address = String(graphNode.node?.address || '').trim();
                    const room = String(graphNode.node?.room || '').trim();
                    if (address) this._appendFnMapPopupLine(popup, `Address: ${address}`);
                    if (room) this._appendFnMapPopupLine(popup, `Room: ${room}`);
                    const basis = graphNode.node?.role_basis;
                    if (basis) this._appendFnMapPopupLine(popup, `Role evidence: ${basis}`, 'text-muted small');
                }
                this._appendFnMapPopupLine(
                    popup,
                    `${graphNode.coordinates.lat.toFixed(6)}, ${graphNode.coordinates.lon.toFixed(6)}`,
                    'text-muted small'
                );
                marker.bindPopup(popup);
                bounds.push([graphNode.coordinates.lat, graphNode.coordinates.lon]);
            }

            this.fnSelectedMapPathStatus = {
                loading: false,
                error: pathError,
                snapshotDate,
                pathCount: resolvedPathCount,
                segmentCount: graphEdges.size,
                missingCoordinateCount: missingCoordinateKeys.size,
                unresolvedCount,
            };
            if (bounds.length === 1) map.setView(bounds[0], 17);
            else if (bounds.length > 1) map.fitBounds(bounds, { padding: [30, 30], maxZoom: 17 });
            setTimeout(() => map.invalidateSize(), 0);
        },

        async renderFnSelectedMap() {
            if (!this.fnSelectedMapVisible) return;
            const mapElement = this.$refs.fnSelectedModemMap;
            const points = this.fnScanSelectedMappableModems;
            if (!mapElement || !points.length) {
                this._destroyFnSelectedMap();
                return;
            }
            if (!window.L) {
                this.$toast?.error('The map renderer could not be loaded');
                this.fnSelectedMapVisible = false;
                return;
            }

            if (this._fnSelectedMapRequestController) this._fnSelectedMapRequestController.abort();
            const generation = (this._fnSelectedMapRenderGeneration || 0) + 1;
            this._fnSelectedMapRenderGeneration = generation;
            const controller = new AbortController();
            this._fnSelectedMapRequestController = controller;
            this.fnSelectedMapPathStatus = {
                loading: true,
                error: '',
                snapshotDate: '',
                pathCount: 0,
                segmentCount: 0,
                missingCoordinateCount: 0,
                unresolvedCount: 0,
            };

            let pathPayload = { snapshot_date: '', paths: [] };
            let pathError = '';
            try {
                const response = await fetch(`${API_BASE}/topology/paths/by-modems`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        mac_addresses: points.map(point => point.mac_address),
                        max_hops: 32,
                    }),
                    signal: controller.signal,
                });
                const data = await response.json();
                if (!response.ok || data?.status !== 'success') {
                    throw new Error(data?.message || data?.detail || `Topology path request failed (${response.status})`);
                }
                pathPayload = data;
            } catch (error) {
                if (error?.name === 'AbortError') return;
                pathError = error?.message || 'Topology paths could not be resolved.';
            } finally {
                if (this._fnSelectedMapRequestController === controller) {
                    this._fnSelectedMapRequestController = null;
                }
            }
            if (!this.fnSelectedMapVisible || generation !== this._fnSelectedMapRenderGeneration) return;
            this._drawFnSelectedMap(points, pathPayload, pathError);
        },

        hasActiveUiTask() {
            return !!(
                this.runningTest ||
                this.runningUtsc ||
                this.runningUsRxmer ||
                this.runningFiberNode ||
                this.fnScanRunning ||
                this.fnImpulseRunning ||
                this.dsScanRunning ||
                this.fbScanRunning ||
                this.liveSpectrumEnabled
            );
        },

        isTaskButtonDisabled(taskName) {
            return this.runningTest && this.activeMeasurement === taskName;
        },

        _clearUiTaskTimers() {
            if (this._utscPollTimer) { clearTimeout(this._utscPollTimer); this._utscPollTimer = null; }
            if (this._usRxmerPollTimer) { clearTimeout(this._usRxmerPollTimer); this._usRxmerPollTimer = null; }
            if (this._fnScanPollTimer) { clearInterval(this._fnScanPollTimer); this._fnScanPollTimer = null; }
            if (this._fnScanWaitTimer) { clearInterval(this._fnScanWaitTimer); this._fnScanWaitTimer = null; }
            if (this._dsPollTimer) { clearInterval(this._dsPollTimer); this._dsPollTimer = null; }
            if (this._fbPollTimer) { clearInterval(this._fbPollTimer); this._fbPollTimer = null; }
            if (this.liveSpectrumIntervalId) { clearInterval(this.liveSpectrumIntervalId); this.liveSpectrumIntervalId = null; }
        },

        _beginUiTask(taskLabel, measurementName = null) {
            this._taskGeneration += 1;
            if (this._currentFetchController) {
                try { this._currentFetchController.abort(); } catch (_) {}
            }
            this._currentFetchController = new AbortController();
            this._activeTaskLabel = taskLabel;
            if (measurementName) {
                this.runningTest = true;
                this.activeMeasurement = measurementName;
            }
            return { token: this._taskGeneration, signal: this._currentFetchController.signal };
        },

        _isTaskActive(token) {
            return token === this._taskGeneration;
        },

        async prepareUiTask(taskLabel) {
            if (!this.hasActiveUiTask()) return true;
            const current = this._activeTaskLabel || this.activeMeasurement || 'current task';
            if (current === taskLabel) return true;
            const confirmed = window.confirm(`Cancel current task (${current}) and start ${taskLabel}?`);
            if (!confirmed) return false;
            await this.cancelActiveUiTasks({ silent: true, stopBackend: true });
            return true;
        },

        async cancelActiveUiTasks({ silent = false, stopBackend = true } = {}) {
            const impulseJobIdToCancel = stopBackend && this.fnImpulseRunning ? this.fnImpulseJobId : null;
            this._taskGeneration += 1;
            if (this._currentFetchController) {
                try { this._currentFetchController.abort(); } catch (_) {}
                this._currentFetchController = null;
            }
            this._clearUiTaskTimers();

            const shouldStopUtsc = stopBackend && this.selectedModem?.cmts_ip && this.utscConfig?.rfPortIfindex && (this.runningUtsc || this.liveSpectrumEnabled);

            this.runningTest = false;
            this.activeMeasurement = null;
            this._activeTaskLabel = null;
            this.runningUtsc = false;
            this.runningUsRxmer = false;
            this.runningFiberNode = false;
            this.fnScanRunning = false;
            this.fnImpulseRunning = false;
            this.fnImpulseJobId = null;
            if (this.fnImpulseProgress && !this.fnImpulseProgress.done) {
                this.fnImpulseProgress = {
                    ...this.fnImpulseProgress,
                    state: 'aborted',
                    action: 'Cancelled',
                    running_count: 0,
                    queued_count: 0,
                    done: true,
                };
            }
            this.dsScanRunning = false;
            this.fbScanRunning = false;
            this.liveSpectrumEnabled = false;
            this.liveSpectrumPolling = false;

            if (impulseJobIdToCancel) {
                try {
                    await fetch(
                        `${API_BASE}/pypnm/impulse-response/fibernode/jobs/${encodeURIComponent(impulseJobIdToCancel)}`,
                        { method: 'DELETE' }
                    );
                } catch (_) {}
            }

            if (shouldStopUtsc) {
                try { await this.stopUtsc(); } catch (_) {}
            }

            if (!silent) this.$toast?.info('Current task cancelled');
        },

        // Format large integers with comma thousands-separator (no locale dot confusion)
        fmtN(n) {
            if (n == null) return '\u2014';
            return Number(n).toLocaleString('en-US');
        },

        profileLabel(profileId) {
            const id = Number(profileId);
            if (!Number.isFinite(id)) return String(profileId ?? '\u2014');
            // Profile 0 = A (lowest: QAM-256), 3 = D (highest: QAM-4096+)
            const labels = { 0: 'A', 1: 'B', 2: 'C', 3: 'D' };
            return labels[id] ?? String(id);
        },

        displayedDownstreamProfile(channelRow) {
            const currentProfile = Number(channelRow?.current_profile);
            return Number.isFinite(currentProfile) ? currentProfile : null;
        },

        countPartialProfiles(dsProfiles) {
            if (!Array.isArray(dsProfiles)) return 0;
            let count = 0;
            for (const ch of dsProfiles) {
                const profiles = ch?.profiles || [];
                for (const p of profiles) {
                    if ((p?.partial_reason_code || 0) > 0) count += 1;
                }
            }
            return count;
        },

        countChannelsWithPartial(dsProfiles) {
            if (!Array.isArray(dsProfiles)) return 0;
            let count = 0;
            for (const ch of dsProfiles) {
                const profiles = ch?.profiles || [];
                if (profiles.some(p => (p?.partial_reason_code || 0) > 0)) count += 1;
            }
            return count;
        },

        _resolveCurrentIuc(channelRow) {
            const explicitCurrentIuc = Number(channelRow?.current_iuc);
            if (Number.isFinite(explicitCurrentIuc)) {
                return explicitCurrentIuc;
            }
            return null;
        },

        isActiveIuc(iucRow, channelRow) {
            const activeIuc = this._resolveCurrentIuc(channelRow);
            if (!Number.isFinite(activeIuc)) return false;
            return Number(iucRow?.iuc || 0) === activeIuc;
        },

        _resolveCurrentProfile(channelRow) {
            const explicitCurrentProfile = Number(channelRow?.current_profile);
            if (Number.isFinite(explicitCurrentProfile)) {
                return explicitCurrentProfile;
            }
            return null;
        },

        isActiveProfile(profileRow, channelRow = null) {
            const currentProfile = this._resolveCurrentProfile(channelRow);
            if (Number.isFinite(currentProfile)) {
                return Number(profileRow?.profile_id) === currentProfile;
            }
            return false;
        },

        profileBadgeClass(profileRow, channelRow = null) {
            return this.isActiveProfile(profileRow, channelRow) ? 'badge bg-success' : 'badge bg-secondary';
        },

        iucBadgeClass(iucRow, channelRow) {
            return this.isActiveIuc(iucRow, channelRow) ? 'badge bg-success' : 'badge bg-secondary';
        },

        channelHasPartial(channelRow) {
            const rows = channelRow?.profiles || [];
            return rows.some(p => (Number(p?.partial_reason_code || 0) > 0) || (Number(p?.last_partial_reason_code || 0) > 0));
        },

        formatPlotTitle(filename) {
            // Convert filename to readable title
            // e.g. "ds_ofdm_rxmer_per_subcar_44053f93f43b_33_1772694262.bin.png" -> "DS OFDM RxMER — Ch 33"
            const cleanName = filename.replace(/\.png$/i, '').replace(/\.bin$/i, '');
            const parts = cleanName.split('_');

            const channel = parts.find(p => p.match(/^\d{1,3}$/) && parseInt(p) < 300);

            if (cleanName.includes('ds_ofdm') && cleanName.includes('rxmer')) {
                return channel ? `DS OFDM RxMER — Ch ${channel}` : 'DS OFDM RxMER';
            } else if (cleanName.includes('us_ofdma') && cleanName.includes('rxmer')) {
                return channel ? `US OFDMA RxMER — Ch ${channel}` : 'US OFDMA RxMER';
            } else if (cleanName.includes('rxmer')) {
                return channel ? `RxMER — Ch ${channel}` : 'RxMER';
            } else if (cleanName.includes('modulation_count') || cleanName.includes('modprof')) {
                return channel ? `Modulation Profile — Ch ${channel}` : 'Modulation Profile';
            } else if (cleanName.includes('signal_aggregate')) {
                return 'Signal Aggregate (All Channels)';
            } else if (cleanName.includes('channel_est') || cleanName.includes('chanest')) {
                return channel ? `Channel Estimation — Ch ${channel}` : 'Channel Estimation';
            } else if (cleanName.includes('spectrum') || cleanName.includes('utsc')) {
                return 'Upstream Spectrum';
            } else if (cleanName.includes('histogram')) {
                return channel ? `DS Power Histogram — Ch ${channel}` : 'DS Power Histogram';
            } else if (cleanName.includes('constellation')) {
                return channel ? `IQ Constellation — Ch ${channel}` : 'IQ Constellation';
            } else if (cleanName.includes('preeq') || cleanName.includes('pre_eq')) {
                return channel ? `Pre-Equalizer — Ch ${channel}` : 'Pre-Equalizer';
            }

            // Fallback: clean up underscores and title-case
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
                // Pre-populate fiber node scan communities from config
                if (data.snmpCommunity)   this.fnScanCommunity = data.snmpCommunity;
                if (data.snmpCommunityRW) this.fnScanWriteCommunity = data.snmpCommunityRW;
            } catch (e) {
                console.warn(`Could not load server config, using defaults`, e);
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
                        const connectedAgents = (agentData.agents || []).filter(a => a.status === 'connected');
                        const allCaps = connectedAgents.flatMap(a => a.capabilities || []);
                        this.hasCmtsAgent = allCaps.includes('cmts_reachable');
                        this.hasCmAgent   = allCaps.includes('cm_reachable');
                        this.hasFileAgent  = allCaps.includes('pnm_file_get');
                        this.cmtsAgentCount = connectedAgents.filter(a => (a.capabilities||[]).includes('cmts_reachable')).length;
                        this.cmAgentCount   = connectedAgents.filter(a => (a.capabilities||[]).includes('cm_reachable')).length;
                        this.fileAgentCount = connectedAgents.filter(a => (a.agent_id || a.name || '').startsWith('file-agent')).length;
                    } catch (e) {
                        this.agentCount = 0;
                        this.hasCmtsAgent = false;
                        this.hasCmAgent = false;
                        this.hasFileAgent = false;
                        this.cmtsAgentCount = 0;
                        this.cmAgentCount = 0;
                        this.fileAgentCount = 0;
                    }
                } catch (e) {
                    this.pypnmHealthy = false;
                    this.agentCount = 0;
                    this.hasCmtsAgent = false;
                    this.hasCmAgent = false;
                    this.hasFileAgent = false;
                    this.cmtsAgentCount = 0;
                    this.cmAgentCount = 0;
                    this.fileAgentCount = 0;
                }
            } catch (error) {
                console.error('API health check failed:', error);
                this.apiStatus = 'mock';
                this.pypnmHealthy = false;
                this.hasCmtsAgent = false;
                this.hasCmAgent = false;
                this.hasFileAgent = false;
                this.cmtsAgentCount = 0;
                this.cmAgentCount = 0;
                this.fileAgentCount = 0;
            }
        },
        
        async loadCmtsList() {
            try {
                const response = await fetch(`${API_BASE}/cmts`);
                const data = await response.json();
                if (data.status === 'success') {
                    const legacyNameMap = {};
                    // Transform the appdb format to our format
                    const cmtsList = data.cmts_list.map(cmts => ({
                        name: cmts.HostName,
                        ip: cmts.IPAddress,
                        vendor: cmts.Vendor,
                        type: cmts.Type,
                    }));
                    for (const cmts of (data.cmts_list || [])) {
                        const alias = this.normalizeCmtsName(cmts.Alias || '');
                        const hostName = this.normalizeCmtsName(cmts.HostName || '');
                        if (alias && hostName) {
                            legacyNameMap[alias] = hostName;
                        }
                    }
                    this.cmtsLegacyNameMap = legacyNameMap;
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
                    (cmts.name   || '').toLowerCase().includes(search) ||
                    (cmts.ip     || '').toLowerCase().includes(search) ||
                    (cmts.vendor || '').toLowerCase().includes(search)
                );
            }
        },

        async selectSearchCmts(cmts) {
            this.selectedCmts = cmts ? cmts.name : '';
            this.cmtsSearch = '';
            this.cmtsList = this.cmtsListFull;
            this.selectedInterface = '';
            this.modemFilterFn = '';
            this.modemFilterCableMac = '';
            this.modemPage = 1;
            await this.loadCmtsInterfaces();
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
        
        goBack() {
            this.currentView = this.previousView || 'home';
        },

        clearSearchForm() {
            this.searchValue = '';
            this.searchHouseNumber = '';
            this.selectedCmts = '';
            this.selectedInterface = '';
            this.modemFilterFn = '';
            this.modemFilterCableMac = '';
            this.modems = [];
            this.searchPerformed = false;
            this.modemPage = 1;
        },

        async searchModems() {
            this.isLoading = true;
            this.searchPerformed = true;
            
            try {
                // Topology-only search types always go through topology endpoint
                const topologyOnlyTypes = ['fibernode', 'postal_house', 'customer_id'];
                const isTopologyOnlySearch = this.useTopologySearch && topologyOnlyTypes.includes(this.searchType);

                if (isTopologyOnlySearch) {
                    if (this.searchType === 'postal_house' && (!this.searchValue || !this.searchHouseNumber)) {
                        this.showError('Search failed', 'PostalCode and House Number are both required');
                        return;
                    }

                    let searchVal = (this.searchValue || '').trim();
                    if (this.searchType === 'customer_id' && searchVal && !searchVal.match(/^(RES|B2B)-/i)) {
                        searchVal = this.customerIdPrefix + searchVal;
                    }
                    const params = new URLSearchParams({
                        type: this.searchType,
                        value: searchVal,
                        limit: '500',
                    });
                    if (this.searchType === 'postal_house') {
                        params.set('house_number', this.searchHouseNumber || '');
                    }

                    const response = await fetch(`${API_BASE}/topology/search/modems?${params.toString()}`);
                    const data = await response.json();
                    if (data?.status === 'success') {
                        const rows = Array.isArray(data.modems) ? data.modems : [];
                        this.modems = rows.map(m => ({
                            mac_address: this.normalizeMacForDisplay(m.mac || m.mac_address || ''),
                            ip_address: m.ip_address || '',
                            status: m.link_match ? 'topology-matched' : 'topology-only',
                            name: this.normalizeMacForDisplay(m.mac || m.mac_address || ''),
                            vendor: m.vendor || 'Unknown',
                            model: m.model || 'N/A',
                            docsis_version: this.resolveDocsisVersion(m, 'Unknown'),
                            cmts: this.resolveCanonicalCmtsDisplayName(m.cmts_ip || '', m.cmts || ''),
                            cmts_ip: m.cmts_ip || '',
                            cmts_interface: m.cmts_interface || 'N/A',
                            software_version: m.software_version || '',
                            cable_mac: m.cable_mac || '',
                            upstream_interface: m.upstream_interface || '',
                            upstream_ifindex: m.upstream_ifindex ?? null,
                            fiber_node: m.fibernode || '',
                            customer_id: m.customer_id || '',
                            postalcode: m.postalcode || '',
                            house_number: m.house_number || '',
                            house_number_extension: m.house_number_extension || '',
                            lat: m.lat ?? null,
                            lon: m.lon ?? null,
                            topology_path: m.hierarchy_path || '',
                            topology_link_id: m.topology_link_id || '',
                            linked_node_id: m.linked_node_id || '',
                            link_match: Boolean(m.link_match),
                            source: 'topology-search',
                        }));
                        await this._enrichTopologySearchModems(500);
                        this._mergeSearchSeed(this.modems);
                        this.queueSelectedModemEnrichment(this.modems, {
                            scope: 'topology search results',
                            maxBatch: 20,
                        });
                    } else {
                        this.showError('Search failed', data?.message || 'Topology search failed');
                    }
                    return;
                }

                if (this.searchType === 'cpe_ip' && !(this.searchValue || '').trim()) {
                    this.showError('Search failed', 'Enter an IPv4 prefix or a complete IPv6 address');
                    return;
                }

                // MAC / IP / name / CPE searches always hit inventory first (Redis/MySQL = freshest cached data)
                // When topology toggle is on, we also enrich with topology fields afterwards
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
                    this._mergeSearchSeed(this.modems);
                    this.queueSelectedModemEnrichment(this.modems, {
                        scope: 'cable modem search results',
                        maxBatch: 20,
                        cmts: this.selectedCmts,
                    });
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

        async _enrichTopologySearchModems(limit = 250) {
            const rows = Array.isArray(this.modems) ? this.modems.slice(0, limit) : [];
            const targets = rows.filter(m => {
                if (!m?.mac_address) return false;
                const vendorMissing = !m.vendor || m.vendor === 'Unknown';
                const modelMissing = !m.model || m.model === 'N/A';
                const docsisMissing = !m.docsis_version || m.docsis_version === 'Unknown';
                const ofdmMissing = m.ofdm_enabled == null || m.ofdma_enabled == null;
                return !m.ip_address || !m.cmts_ip || vendorMissing || modelMissing || docsisMissing || ofdmMissing;
            });
            if (!targets.length) return;

            const chunks = [];
            const concurrency = 12;
            for (let i = 0; i < targets.length; i += concurrency) {
                chunks.push(targets.slice(i, i + concurrency));
            }

            const patchByMac = {};
            for (const chunk of chunks) {
                const out = await Promise.all(chunk.map(async (m) => {
                    try {
                        const resp = await fetch(`${API_BASE}/modems/${encodeURIComponent(m.mac_address)}`);
                        const data = await resp.json();
                        if (data?.status === 'success' && data.modem) {
                            return { mac: this.normalizeMacForMatch(m.mac_address), modem: data.modem };
                        }
                    } catch (_) {}
                    return null;
                }));
                for (const e of out) {
                    if (e?.mac && e?.modem) patchByMac[e.mac] = e.modem;
                }
            }

            const unresolvedTargets = targets.filter(m => {
                const patch = patchByMac[this.normalizeMacForMatch(m.mac_address)];
                if (!patch) return true;
                const vendorMissing = !patch.vendor || patch.vendor === 'Unknown';
                const modelMissing = !patch.model || patch.model === 'N/A';
                const docsisMissing = !patch.docsis_version || patch.docsis_version === 'Unknown';
                return !patch.ip_address || !patch.cmts_ip || vendorMissing || modelMissing || docsisMissing;
            });

            const groupsByCmts = new Map();
            for (const modem of unresolvedTargets) {
                const cmtsMatch = this.findCmtsMatch(modem.cmts_ip, modem.cmts || modem.cmts_hostname || '');
                const canonicalName = String(cmtsMatch?.name || '').trim();
                if (!canonicalName) continue;
                const entry = groupsByCmts.get(canonicalName) || { cmts: cmtsMatch, modems: [] };
                entry.modems.push(modem);
                groupsByCmts.set(canonicalName, entry);
            }

            for (const [canonicalName, group] of groupsByCmts.entries()) {
                try {
                    const params = new URLSearchParams({
                        community: this.snmpCommunity,
                        limit: String(CM_MODEM_LIMIT),
                    });
                    const response = await fetch(`${API_BASE}/cmts/${encodeURIComponent(canonicalName)}/modems?${params.toString()}`);
                    const data = await response.json();
                    if (data?.status !== 'success' || !Array.isArray(data.modems)) continue;
                    const wantedMacs = new Set(group.modems.map(m => this.normalizeMacForMatch(m.mac_address)).filter(Boolean));
                    for (const modem of data.modems) {
                        const mac = this.normalizeMacForMatch(modem.mac_address);
                        if (!mac || !wantedMacs.has(mac)) continue;
                        patchByMac[mac] = modem;
                    }
                } catch (_) {
                    // Best-effort live CMTS fallback only.
                }
            }

            if (!Object.keys(patchByMac).length) return;
            this.modems = this.modems.map(m => {
                const patch = patchByMac[this.normalizeMacForMatch(m.mac_address)];
                if (!patch) return m;
                const merged = this._mergeModemPreservingCmts({ ...m }, patch);
                return {
                    ...merged,
                    ip_address: m.ip_address || patch.ip_address || '',
                    cmts_ip: m.cmts_ip || patch.cmts_ip || '',
                    cmts: this.resolveCanonicalCmtsDisplayName(m.cmts_ip || patch.cmts_ip || '', m.cmts || patch.cmts || patch.cmts_hostname || ''),
                    status: patch.status || m.status,
                    vendor: patch.vendor || m.vendor,
                    model: patch.model || m.model,
                    software_version: patch.software_version || m.software_version || '',
                    partial_service: this.normalizePartialService(patch.partial_service ?? m.partial_service),
                    partial_service_downstream: patch.partial_service_downstream ?? m.partial_service_downstream ?? null,
                    partial_service_upstream: patch.partial_service_upstream ?? m.partial_service_upstream ?? null,
                    partial_service_state: patch.partial_service_state ?? m.partial_service_state ?? null,
                    cable_mac: patch.cable_mac || m.cable_mac,
                    fiber_node: m.fiber_node || patch.fiber_node || '',
                };
            });
        },

        async prepareTopologyFiberNodeScanTargets() {
            if (!this.useTopologySearch) {
                this.$toast?.info('Enable topology search first');
                return;
            }

            this.fnScanPreparing = true;
            this.fnScanPreparingMessage = 'Loading inventory and topology context…';

            try {
                this._enrichTopologySearchModems(300);

                const candidates = (this.modems || [])
                    .filter(m => m?.mac_address && m?.ip_address && m?.cmts_ip)
                    .map(m => ({
                        mac_address: m.mac_address,
                        ip_address: m.ip_address,
                        cmts_ip: m.cmts_ip,
                        cmts: m.cmts || m.cmts_hostname || '',
                        fiber_node: m.fiber_node || '',
                        upstream_ifindex: m.upstream_ifindex ?? null,
                        md_if_index: m.md_if_index ?? null,
                        upstream_channel_id: m.upstream_channel_id ?? null,
                    }));

                if (!candidates.length) {
                // Try to extract CMTS from topology data even if IP is missing.
                // Topology rows can carry only a CMTS name/path while cmts_ip is blank.
                const topologyModems = (this.modems || []).filter(m => {
                    const pathPart = String(m?.topology_path || '').split('>').map(p => p.trim()).filter(Boolean)[0] || '';
                    return !!(m?.cmts_ip || m?.cmts || m?.cmts_hostname || pathPart);
                });
                let fallbackCmtsIp = '';
                let fallbackCmtsName = '';

                if (topologyModems.length > 0) {
                    const cmtsVotes = {};
                    for (const m of topologyModems) {
                        const pathPart = String(m?.topology_path || '').split('>').map(p => p.trim()).filter(Boolean)[0] || '';
                        const rawName = String(m?.cmts || m?.cmts_hostname || pathPart || '').trim();
                        const rawIp = String(m?.cmts_ip || '').trim();

                        let resolved = null;
                        if (rawIp) {
                            resolved = this.findCmtsMatch(rawIp, rawName);
                        }
                        if (!resolved && rawName) {
                            resolved = this.findCmtsMatch(rawIp, rawName);
                        }

                        const key = (resolved?.ip || rawIp || resolved?.name || rawName || '').trim();
                        if (!key) continue;
                        cmtsVotes[key] = cmtsVotes[key] || {
                            count: 0,
                            ip: resolved?.ip || rawIp || '',
                            name: resolved?.name || rawName || resolved?.ip || rawIp || '',
                        };
                        cmtsVotes[key].count++;
                    }

                    const mostCommon = Object.values(cmtsVotes).sort((a, b) => b.count - a.count)[0];
                    if (mostCommon) {
                        fallbackCmtsIp = mostCommon.ip || '';
                        fallbackCmtsName = mostCommon.name || '';
                    }
                }
                
                // Fallback to selected modem or CMTS if topology didn't provide
                if (!fallbackCmtsIp) {
                    fallbackCmtsIp = (
                        this.selectedModem?.cmts_ip ||
                        this.selectedCmts ||
                        this.fnScanCmtsIp ||
                        ''
                    );
                    fallbackCmtsName = (
                        this.selectedModem?.cmts ||
                        this.selectedModem?.cmts_hostname ||
                        fallbackCmtsIp
                    );
                }

                this.fnScanCommunity = this.fnScanCommunity || this.snmpCommunity;
                this.fnScanWriteCommunity = this.fnScanWriteCommunity || this.snmpCommunityRW;
                this.fnScanUseModemSelector = true;
                this.fnScanSelectedModemMacs = this.selectedModem?.mac_address ? [this.selectedModem.mac_address] : [];
                this.fnScanIfindex = '';
                this.fnScanExtraIfindices = [];
                this.currentView = 'fibernode';

                if (fallbackCmtsIp) {
                    this.fnScanPreparingMessage = 'Loading FiberNode channels…';
                    const cmtsMatch = this.findCmtsMatch(fallbackCmtsIp, fallbackCmtsName);
                    this.fnScanCmts = cmtsMatch || { name: fallbackCmtsName || fallbackCmtsIp, ip: fallbackCmtsIp };
                    this.fnScanCmtsIp = fallbackCmtsIp;
                    await this.loadFnScanChannels();
                    this.fnScanPreparingMessage = 'Loading modem selector list…';
                    await this.refreshFnSelectorModems(true);
                    this.$toast?.warning('No RxMER-ready topology rows (missing IP/CMTS). Opened FiberNode scanner with fallback CMTS context; DS/Fullband tests can still run.');
                } else {
                    this.$toast?.warning('No scan-ready topology rows and no CMTS context found. Opened FiberNode scanner; please select a CMTS manually.');
                }
                return;
                }

                const byCmts = {};
                for (const m of candidates) {
                    byCmts[m.cmts_ip] = byCmts[m.cmts_ip] || [];
                    byCmts[m.cmts_ip].push(m);
                }
                const cmtsChoices = Object.entries(byCmts).sort((a, b) => b[1].length - a[1].length);
                const [scanCmtsIp, selected] = cmtsChoices[0];

                if (cmtsChoices.length > 1) {
                    this.$toast?.info(`Multiple CMTS in results; using ${scanCmtsIp} (${selected.length} modems)`);
                }

                const selectedCmtsName = selected.find(s => s.cmts)?.cmts || '';
                const selectedCmts = this.findCmtsMatch(scanCmtsIp, selectedCmtsName);
                this.fnScanCmts = selectedCmts || { name: selectedCmtsName || scanCmtsIp, ip: scanCmtsIp };
                this.fnScanCmtsIp = scanCmtsIp;
                this.fnScanCommunity = this.fnScanCommunity || this.snmpCommunity;
                this.fnScanWriteCommunity = this.fnScanWriteCommunity || this.snmpCommunityRW;
                this.fnScanUseModemSelector = true;
                this.fnScanSelectedModemMacs = selected.map(m => m.mac_address);
                const selectedMac = this.selectedModem?.mac_address || '';
                const representativeMac = selectedMac || selected[0]?.mac_address || '';
                const preferred = (selected.find(m => m.mac_address === representativeMac) || selected[0] || {});

                // Authoritative selected-modem enrichment for FN/OFDMA labels.
                let selectedModemApi = null;
                if (representativeMac) {
                    try {
                        const er = await fetch(`${API_BASE}/modems/${encodeURIComponent(representativeMac)}`);
                        const ed = await er.json();
                        if (ed?.status === 'success' && ed.modem) {
                            selectedModemApi = ed.modem;
                            if (this.selectedModem?.mac_address && this.selectedModem.mac_address === representativeMac) {
                                this._mergeModemPreservingCmts(this.selectedModem, ed.modem);
                            }
                        }
                    } catch (_) {
                        // Best-effort enrichment only.
                    }
                }
                const uniqueFn = [...new Set(selected.map(m => m.fiber_node).filter(Boolean))];
                const selectedModemFnRaw = (
                    selectedModemApi?.fiber_node ||
                    this.selectedModem?.fiber_node ||
                    this.selectedModem?.fibernode ||
                    preferred.fiber_node ||
                    ''
                ).trim();
                const selectedModemFn = /^FN\d+/i.test(selectedModemFnRaw) ? selectedModemFnRaw : '';
                this.fnScanTopologyBridgeNodeId = selectedModemFn.includes('.') ? selectedModemFn : this.fnScanTopologyBridgeNodeId;
                this.fnScanFiberNode = selectedModemFn || (uniqueFn.length === 1 ? uniqueFn[0] : '');
                this.fnScanIfindex = this._toIfindex(
                    selectedModemApi?.ofdma_ifindex,
                    preferred.ofdma_ifindex,
                    this.selectedModem?.ofdma_ifindex,
                ) || '';
                this.fnScanExtraIfindices = [];
                this.currentView = 'fibernode';

                this.fnScanPreparingMessage = 'Loading FiberNode channels…';
                await this.loadFnScanChannels();
                this.fnScanPreparingMessage = 'Loading modem selector list…';
                await this.refreshFnSelectorModems(true);

                let preferredIfindex = this._toIfindex(
                    selectedModemApi?.ofdma_ifindex,
                    preferred.ofdma_ifindex,
                    this.selectedModem?.ofdma_ifindex,
                );

            // If selector refresh has fresher modem fields, use those as tie-breaker.
                if (!preferredIfindex && selectedMac) {
                    const refreshed = (this.modems || []).find(m => m.mac_address === selectedMac) || {};
                    preferredIfindex = this._toIfindex(
                        refreshed.ofdma_ifindex,
                    );
                }

            // Authoritative fallback: query CMTS per-modem upstream discovery.
                if (!preferredIfindex) {
                    preferredIfindex = await this._discoverPreferredOFDMAIfindex(preferred.mac_address || selectedMac, scanCmtsIp);
                }

            // The topology fiber node label (e.g., RT19....) can differ from
            // discovery fiber node labels (e.g., FN19). If current label is not
            // present in discovered options, derive FN from preferred ifindex.
                const discoveredFnNames = new Set((this.fnScanFiberNodes || []).map(f => f.name));
                // If current label is not FNxx (e.g. RT topology label), prefer mapped FN label.
                if (preferredIfindex) {
                    const mappedFn = this.fnNameForIfindex(preferredIfindex);
                    if (mappedFn && (!this.fnScanFiberNode || !/^FN\d+/i.test(this.fnScanFiberNode))) {
                        this.fnScanFiberNode = mappedFn;
                    }
                }

                if (this.fnScanFiberNode) {
                    const fn = (this.fnScanFiberNodes || []).find(f => f.name === this.fnScanFiberNode);
                    if (fn && fn.channels && fn.channels.length) {
                        const fnIfs = fn.channels.map(c => parseInt(c.ifindex, 10)).filter(Boolean);
                        if (preferredIfindex && fnIfs.includes(preferredIfindex)) {
                            this.fnScanIfindex = preferredIfindex;
                            this.fnScanExtraIfindices = fnIfs.filter(i => i !== preferredIfindex);
                        } else {
                            this.fnScanIfindex = fnIfs[0] || '';
                            this.fnScanExtraIfindices = fnIfs.slice(1);
                        }
                    }
                }

                if (!this.fnScanIfindex && preferredIfindex) {
                    this.fnScanIfindex = preferredIfindex;
                }

                if (!this.fnScanIfindex && this.fnScanChannels && this.fnScanChannels.length) {
                    this.fnScanIfindex = this.fnScanChannels[0].ifindex;
                }

                if (this.fnScanIfindex) {
                    this.loadFnModemCount();
                }

                this.$toast?.info('Topology handoff uses selected modem set. Choose a FiberNode manually if desired.');

                const preparedCount = this.fnScanUseModemSelector
                    ? this.fnScanSelectedModemMacs.length
                    : (Number(this.fnScanModemCount) || 0);
                this.$toast?.success(`FiberNode scan context prepared with ${preparedCount} modem(s)`);
            } finally {
                this.fnScanPreparing = false;
                this.fnScanPreparingMessage = '';
            }
        },
        
        async getLiveModems() {
            if (!this.selectedCmts) {
                this.showError('Select CMTS', 'Please select a CMTS first');
                return;
            }
            
            this.loadingLiveModems = true;
            this.liveModemSource = '';
            this.liveCachePartial = false;
            this.liveCacheRefreshing = false;
            this.liveInventoryComplete = false;
            this.liveInventoryStale = false;
            this.liveCapabilityEnriched = false;
            this.enrichmentProgress = { current: 0, total: 0 };
            this.modemPage = 1;
            this.loadProgress = 0;
            const loadToken = Date.now();
            this._liveLoadToken = loadToken;
            this.pendingFullLoadUrl = null;
            this.pendingFullLoadToken = null;
            this._mapLiveModem = null;
            // Cancel any in-progress enrichment poll from a previous load
            if (this._enrichPollTimer) { clearTimeout(this._enrichPollTimer); this._enrichPollTimer = null; }
            this.isEnriching = false;
            // Fake walk-phase progress: 0→90% over ~2.5 min, smooth 1% every 1.6s
            if (this._progressTimer) clearInterval(this._progressTimer);
            this._progressTimer = setInterval(() => {
                if (this.loadProgress < 90) this.loadProgress++;
            }, 1600);
            
            try {
                const buildUrl = (limit, enrichEnabled, forceRefresh = false) => {
                    // This same-origin API uses configured server-side communities.
                    // Never put SNMP credentials in browser URLs or access logs.
                    const boundedLimit = Math.max(1, Math.min(Number(limit) || CM_MODEM_LIMIT, 50000));
                    let u = `${API_BASE}/cmts/${encodeURIComponent(this.selectedCmts)}/modems?limit=${boundedLimit}`;
                    u += `&enrich=${enrichEnabled ? 'true' : 'false'}`;
                    if (forceRefresh) u += '&refresh=true';
                    return u;
                };

                const mapModem = (m, resp) => {
                    const row = {
                        mac_address: m.mac_address,
                        ip_address: m.ip_address,
                        status: m.status || 'unknown',
                        status_code: m.status_code ?? null,
                        name: m.mac_address,
                        vendor: m.vendor || 'Unknown',
                        model: m.model || 'N/A',
                        docsis_version: m.docsis_version || 'Unknown',
                        cmts: resp.cmts_hostname,
                        cmts_ip: resp.cmts_ip,
                        cmts_index: m.cmts_index ?? null,
                        docsif3_index: m.docsif3_index ?? null,
                        cmts_interface: m.interface || m.cmts_index || 'N/A',
                        software_version: m.software_version || '',
                        cable_mac: m.cable_mac || '',
                        upstream_interface: m.upstream_interface || '',
                        ofdma_interface: m.ofdma_interface || '',
                        interface_name: m.interface_name || '',
                        upstream_ifindex: m.upstream_ifindex ?? null,
                        fiber_node: m.fiber_node || '',
                        partial_service: this.normalizePartialService(m.partial_service),
                        partial_service_downstream: m.partial_service_downstream ?? null,
                        partial_service_upstream: m.partial_service_upstream ?? null,
                        partial_service_state: m.partial_service_state ?? null,
                        ofdma_enabled: m.ofdma_enabled ?? null,
                        ofdma_ifindex: m.ofdma_ifindex ?? null,
                        ofdma_rf_port_ifindex: m.ofdma_rf_port_ifindex ?? null,
                        upstream_ofdma_ifindex: m.upstream_ofdma_ifindex ?? null,
                        ofdm_enabled: m.ofdm_enabled ?? null,
                        ofdm_ifindex: m.ofdm_ifindex ?? null,
                        ofdm_rf_port_ifindex: m.ofdm_rf_port_ifindex ?? null,
                        downstream_ofdm_ifindex: m.downstream_ofdm_ifindex ?? null,
                        ofdm_channels: m.ofdm_channels ?? null,
                        ofdma_channels: m.ofdma_channels ?? null,
                        downstream_ofdm_channels: m.downstream_ofdm_channels ?? null,
                        upstream_ofdma_channels: m.upstream_ofdma_channels ?? null,
                        ofdm: m.ofdm ?? null,
                        ofdma: m.ofdma ?? null,
                        downstream: m.downstream ?? null,
                        upstream: m.upstream ?? null,
                        ofdm_count: m.ofdm_count ?? null,
                        ofdma_count: m.ofdma_count ?? null,
                        downstream_ofdm_count: m.downstream_ofdm_count ?? null,
                        upstream_ofdma_count: m.upstream_ofdma_count ?? null,
                        ofdm_channel_count: m.ofdm_channel_count ?? null,
                        ofdma_channel_count: m.ofdma_channel_count ?? null,
                    };
                    return this._mergeModemPreservingCmts(row, {});
                };

                const cmtsKey = String(this.selectedCmts || '').trim();
                const forcePreviewRefresh = !!this._forceNextLiveRefreshByCmts[cmtsKey];
                if (forcePreviewRefresh && cmtsKey) delete this._forceNextLiveRefreshByCmts[cmtsKey];

                // Phase 1: quick preview (first page only, no enrichment — speed matters).
                const PRELOAD_COUNT = 200;
                const preview = await this._fetchJsonWithTimeout(buildUrl(PRELOAD_COUNT, false, forcePreviewRefresh), 180000);

                if (preview.status !== 'success') {
                    this.showError('Failed to get modems', preview.message || 'Unknown error');
                    return;
                }

                if (this._liveLoadToken !== loadToken) return;

                const previewRaw = Array.isArray(preview.modems) ? preview.modems : [];
                const previewVisible = this._filterBySelectedInterface(previewRaw);
                this.modems = previewVisible.map(m => mapModem(m, preview));
                this._mergeSearchSeed(this.modems);
                this.searchPerformed = true;
                this.liveModemSource = `Inventory preview from ${preview.cmts_hostname} (${preview.cmts_ip}) - ${this.modems.length}/${preview.count} modems (first page loaded)`;
                this.liveCachePartial = Boolean(preview?.partial);
                this.liveInventoryComplete = preview?.inventory_complete === true;
                this.liveInventoryStale = preview?.inventory_stale === true;
                this.liveCapabilityEnriched = preview?.capability_enriched === true;

                // Continue the complete persisted base inventory load without
                // metadata-driven enrichment or forced refresh.
                if (this._progressTimer) { clearInterval(this._progressTimer); this._progressTimer = null; }
                this.loadProgress = 100;
                this.loadingLiveModems = false;
                this.liveCacheRefreshing = false;
                this._loadAllModemsInBackground(buildUrl(CM_MODEM_LIMIT, false, false), mapModem, loadToken);
                return;
            } catch (error) {
                if (error?.name === 'AbortError' || String(error?.message || '').toLowerCase().includes('timed out')) {
                    console.warn('Live modem request timed out:', error);
                    this.showError('Failed to get modems', 'Request timed out while loading live modems. Please retry.');
                } else {
                    console.error('Failed to get live modems:', error);
                    this.showError('Failed to get modems', error.message);
                }
            } finally {
                if (this._progressTimer) { clearInterval(this._progressTimer); this._progressTimer = null; }
                this.loadProgress = 100;
                this.loadingLiveModems = false;
                // Keep progress visible during enrichment.
                if (!this.isEnriching) {
                    this.enrichmentProgress = { current: 0, total: 0 };
                }
            }
        },

        _maybeStartDeferredFullLoad() {
            if (!this.pendingFullLoadUrl || !this.pendingFullLoadToken || !this._mapLiveModem) return;
            if (this.modemPage <= 1) return;

            const url = this.pendingFullLoadUrl;
            const token = this.pendingFullLoadToken;
            const mapper = this._mapLiveModem;
            this.pendingFullLoadUrl = null;
            this.pendingFullLoadToken = null;

            this._loadAllModemsInBackground(url, mapper, token);
        },

        async _fetchJsonWithTimeout(url, timeoutMs = 90000) {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), timeoutMs);
            try {
                const response = await fetch(url, { signal: controller.signal });
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                return await response.json();
            } catch (error) {
                if (error?.name === 'AbortError') {
                    throw new Error(`Request timed out after ${Math.ceil(timeoutMs / 1000)}s`);
                }
                throw error;
            } finally {
                clearTimeout(timer);
            }
        },

        _filterBySelectedInterface(rows) {
            const iface = String(this.selectedInterface || '').trim().toLowerCase();
            if (!iface) return rows || [];
            return (rows || []).filter(m => {
                const candidates = [
                    m?.interface,
                    m?.cmts_interface,
                    m?.upstream_interface,
                    m?.cable_mac,
                ].map(value => String(value || '').trim().toLowerCase());
                return candidates.some(value => value.includes(iface));
            });
        },

        async _loadAllModemsInBackground(url, mapModem, loadToken) {
            try {
                const data = await this._fetchJsonWithTimeout(url, 180000);
                if (data.status !== 'success') {
                    throw new Error(data?.message || 'Background inventory load failed');
                }
                if (this._liveLoadToken !== loadToken) return;

                const CHUNK_SIZE = 200;
                const rawModems = Array.isArray(data.modems) ? data.modems : [];
                const existingByMac = new Map();
                for (const modem of (this.modems || [])) {
                    const norm = this.normalizeMacForMatch(modem?.mac_address || '');
                    if (norm) existingByMac.set(norm, modem);
                }

                const mapped = rawModems.map(m => {
                    const row = mapModem(m, data);
                    const norm = this.normalizeMacForMatch(row?.mac_address || '');
                    const prev = norm ? existingByMac.get(norm) : null;
                    if (!prev) return row;

                    // Non-enriched refresh responses can regress known capability
                    // fields to false/null. Reconcile through the monotonic merge.
                    return this._mergeModemPreservingCmts({ ...prev }, row);
                });
                const visibleMapped = this._filterBySelectedInterface(mapped);
                this._mergeSearchSeed(visibleMapped);
                // Identity enrichment is selection-scoped and starts from the
                // initial preview/search rows. Never probe the full CMTS list.

                // Append the complete dataset in chunks to avoid freezing the UI.
                // Selected interface/FN/Cable-MAC values are display filters only.
                this.modems = [];
                let nextIdx = 0;
                const appendChunk = () => {
                    if (this._liveLoadToken !== loadToken) return;
                    if (nextIdx >= visibleMapped.length) return;
                    this.modems.push(...visibleMapped.slice(nextIdx, nextIdx + CHUNK_SIZE));
                    nextIdx += CHUNK_SIZE;
                    if (nextIdx < visibleMapped.length) setTimeout(appendChunk, 0);
                };
                appendChunk();

                if (data.enrichment_progress) {
                    this.enrichmentProgress = {
                        current: data.enrichment_progress.completed || 0,
                        total: data.enrichment_progress.total || data.count,
                    };
                }

                const cacheInfo = data.cached ? ' (persisted)' : '';
                const enrichInfo = data.enriched === true ? ' [enriched]' : (data.enriching === true ? ' [enriching in background...]' : '');
                this.liveModemSource = `Inventory from ${data.cmts_hostname} (${data.cmts_ip}) - ${data.count} modems${cacheInfo}${enrichInfo}`;
                this.liveCachePartial = Boolean(data.partial);
                this.liveInventoryComplete = data.inventory_complete === true;
                this.liveInventoryStale = data.inventory_stale === true;
                this.liveCapabilityEnriched = data.capability_enriched === true;
                this.liveCacheRefreshing = data.enriching === true;
                if (this.enrichModems && !this.liveCachePartial && data.enriched !== true && data.enriching !== true) await this._requestDeltaEnrichmentForSelectedCmts();
                if (this.enrichModems && data.enriched !== true && data.enriching === true) {
                    if (data.enrichment_progress && data.enrichment_progress.total > 0) this.enrichmentProgress = { current: data.enrichment_progress.completed || 0, total: data.enrichment_progress.total };
                    this.isEnriching = true;
                    this._enrichBatch1Refreshed = false;
                    this._enrichPollAttempts = 0;
                    this._scheduleEnrichPoll();
                } else this._stopEnrichmentPolling(data.enriched === true ? 'backend reports enriched' : 'backend reports not enriching');
            } catch (error) {
                console.warn('Background full modem load failed:', error?.message || error);
                this._stopEnrichmentPolling('background load error');
                if (this._liveLoadToken !== loadToken) return;
                this.liveCacheRefreshing = false;
                this.liveCachePartial = true;
                const reason = String(error?.message || '').toLowerCase().includes('timed out')
                    ? 'timed out'
                    : 'failed';
                this.liveModemSource = `${this.liveModemSource} — preview only; full load ${reason}`;
                this.$toast?.warning(`Full modem inventory ${reason}; the preview remains available.`);
            }
        },
        
        _scheduleEnrichPoll() {
            if (!this.isEnriching) return;
            const MAX_ATTEMPTS = 60;  // 60 × 2s = 2 min max
            const POLL_INTERVAL_MS = 2000;
            if (this._enrichPollAttempts >= MAX_ATTEMPTS) {
                console.warn('Enrichment polling gave up after', MAX_ATTEMPTS, 'attempts');
                this._stopEnrichmentPolling('max attempts reached');
                return;
            }
            // Reset any previous timer.
            if (this._enrichPollTimer) { clearTimeout(this._enrichPollTimer); this._enrichPollTimer = null; }
            const nextAttempt = this._enrichPollAttempts + 1;
            this._enrichPollAttempts = nextAttempt;
            this._enrichPollTimer = setTimeout(async () => {
                this._enrichPollTimer = null;
                const done = await this.refreshEnrichedModems();
                if (!done && this.isEnriching) this._scheduleEnrichPoll();
            }, POLL_INTERVAL_MS);
        },

        _stopEnrichmentPolling(reason = '') {
            if (this._enrichPollTimer) { clearTimeout(this._enrichPollTimer); this._enrichPollTimer = null; }
            this.isEnriching = false;
            this.enrichmentProgress = { current: 0, total: 0 };
            if (reason) console.log('Enrichment polling stopped:', reason);
        },

        async refreshEnrichedModems() {
            // Refresh enriched data without showing the loading spinner.
            if (!this.selectedCmts) {
                this._stopEnrichmentPolling('no CMTS selected');
                return true;
            }

            // Pause while modem-detail context is active to avoid poller contention.
            // Enrichment resumes once user leaves modem detail view.
            const inModemDetailContext = this.currentView === 'modems' && !!this.selectedModem;
            if (this.channelStatsLoading || this.upstreamInterfaces?.loading || inModemDetailContext) return false;

            try {
                // Poll explicit enrichment state; never force a base refresh.
                const url = `${API_BASE}/cmts/${encodeURIComponent(this.selectedCmts)}/modems?limit=${CM_MODEM_LIMIT}&enrich=true`;

                const data = await this._fetchJsonWithTimeout(url, 120000);

                if (data.status === 'success' && data.modems) {
                    // Always update progress bar from the latest poll response
                    if (data.enrichment_progress && data.enrichment_progress.total > 0) {
                        this.enrichmentProgress = {
                            current: data.enrichment_progress.completed || 0,
                            total: data.enrichment_progress.total
                        };
                    }

                    // Patch enriched fields in-place by MAC address
                    const patchMap = {};
                    for (const m of data.modems) {
                        patchMap[this.normalizeMacForMatch(m.mac_address)] = m;
                    }

                    for (const modem of this.modems) {
                        const updated = patchMap[this.normalizeMacForMatch(modem.mac_address)];
                        if (!updated) continue;
                        this._mergeModemPreservingCmts(modem, {
                            ...updated,
                            cable_mac: updated.cable_mac || modem.cable_mac,
                            upstream_interface: updated.upstream_interface || modem.upstream_interface,
                            fiber_node: updated.fiber_node || modem.fiber_node,
                            vendor: updated.vendor || modem.vendor,
                            model: updated.model || modem.model,
                            software_version: updated.software_version || modem.software_version,
                            partial_service_downstream: updated.partial_service_downstream ?? modem.partial_service_downstream,
                            partial_service_upstream: updated.partial_service_upstream ?? modem.partial_service_upstream,
                            partial_service_state: updated.partial_service_state ?? modem.partial_service_state,
                        });
                        modem.partial_service = this.normalizePartialService(updated.partial_service ?? modem.partial_service);
                    }
                    // New shallow array ref forces Vue computed props to recompute
                    // and re-render rows with updated vendor/model/docsis fields.
                    this.modems = this.modems.slice();

                    // Patch selectedModem in-place too — don't replace the reference
                    if (this.selectedModem) {
                        const updatedSel = patchMap[this.normalizeMacForMatch(this.selectedModem.mac_address)];
                        if (updatedSel) {
                            this._mergeModemPreservingCmts(this.selectedModem, {
                                ...updatedSel,
                                cable_mac: updatedSel.cable_mac || this.selectedModem.cable_mac,
                                upstream_interface: updatedSel.upstream_interface || this.selectedModem.upstream_interface,
                                fiber_node: updatedSel.fiber_node || this.selectedModem.fiber_node,
                                vendor: updatedSel.vendor || this.selectedModem.vendor,
                                model: updatedSel.model || this.selectedModem.model,
                                software_version: updatedSel.software_version || this.selectedModem.software_version,
                                partial_service_downstream: updatedSel.partial_service_downstream ?? this.selectedModem.partial_service_downstream,
                                partial_service_upstream: updatedSel.partial_service_upstream ?? this.selectedModem.partial_service_upstream,
                                partial_service_state: updatedSel.partial_service_state ?? this.selectedModem.partial_service_state,
                            });
                            this.selectedModem.partial_service = this.normalizePartialService(
                                updatedSel.partial_service ?? this.selectedModem.partial_service
                            );
                        }
                    }

                    // Backend enriching=false is terminal even if an old
                    // progress object remains attached to the response.
                    if (data.enriched === true) {
                        this.liveModemSource = `Inventory from ${data.cmts_hostname} (${data.cmts_ip}) - ${data.count} modems [enriched ✓]`;
                        this._stopEnrichmentPolling('backend reports enriched');
                        if (this.selectedCmts) {
                            fetch(`${API_BASE}/cmts/${encodeURIComponent(this.selectedCmts)}/cache/refresh`, { method: 'POST' })
                                .catch(() => {});
                        }
                        return true;
                    }
                    if (data.enriching === false) {
                        this.liveModemSource = `Inventory from ${data.cmts_hostname} (${data.cmts_ip}) - ${data.count} modems`;
                        this._stopEnrichmentPolling('backend reports not enriching');
                        return true;
                    }
                } else {
                    throw new Error(data?.message || 'Enrichment poll failed');
                }
            } catch (error) {
                console.warn('Silent refresh failed:', error);
                this._stopEnrichmentPolling('poll error');
                return true;
            }
            return false;
        },
        
        async stopEnrichment() {
            this._stopEnrichmentPolling('manual stop requested');
            if (this.selectedCmts) {
                try {
                    await fetch(`${API_BASE}/cmts/enrich/cancel?cmts_ip=${encodeURIComponent(this.selectedCmts)}`, { method: 'POST' });
                } catch (e) { /* ignore network errors */ }
            }
        },

        async clearCmtsCache() {
            if (!this.selectedCmts) return;
            try {
                const response = await fetch(`${API_BASE}/cmts/${encodeURIComponent(this.selectedCmts)}/cache/clear`, { method: 'POST' });
                const data = await response.json();
                if (data.status === 'success') {
                    const cmtsKey = String(this.selectedCmts || '').trim();
                    if (cmtsKey) this._forceNextLiveRefreshByCmts[cmtsKey] = true;
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
            this.searchHouseNumber = '';
            this.topologySuggestions = [];
            this.selectedCmts = '';
            this.selectedInterface = '';
            this.cmtsInterfaces = [];
            this.liveModemSource = '';
            this.searchModems();
        },

        _buildFallbackFiberNodesFromModems(cmtsIp) {
            const byFn = {};
            for (const m of (this.modems || [])) {
                if (!m?.fiber_node) continue;
                if (cmtsIp && m?.cmts_ip && m.cmts_ip !== cmtsIp) continue;
                const fn = String(m.fiber_node).trim();
                if (!fn) continue;
                byFn[fn] = (byFn[fn] || 0) + 1;
            }
            return Object.entries(byFn)
                .sort((a, b) => a[0].localeCompare(b[0]))
                .map(([name, count]) => ({
                    name,
                    mac_domain: name,
                    channels: [],
                    modem_count: count,
                }));
        },

        _ensureFiberNodeInScanList(fnName, ifindex = null, opts = {}) {
            const name = String(fnName || '').trim();
            if (!name) return;

            if (!Array.isArray(this.fnScanFiberNodes)) this.fnScanFiberNodes = [];
            let fn = this.fnScanFiberNodes.find(f => f.name === name);
            if (!fn) {
                fn = { name, mac_domain: name, channels: [], modem_count: null };
                this.fnScanFiberNodes.push(fn);
            }

            const idx = this._toIfindex(ifindex);
            if (!idx) return;
            if (!Array.isArray(fn.channels)) fn.channels = [];
            const existIdx = fn.channels.findIndex(c => this._toIfindex(c?.ifindex) === idx);
            if (existIdx === -1) {
                const known = (this.fnScanChannels || []).find(c => this._toIfindex(c?.ifindex) === idx);
                fn.channels.push(known || {
                    ifindex: idx,
                    description: opts?.description || `OFDMA ${idx}`,
                    mac_domain: name,
                    modem_count: null,
                });
            } else if (opts?.description && fn.channels[existIdx].description?.match(/^OFDMA \d+$/)) {
                // Upgrade a generic description with the real channel name
                fn.channels[existIdx].description = opts.description;
            }
        },

        async primeFnScanFromSelectedModem(modem) {
            if (!modem?.mac_address) return;
            this._fnTrace('prime.start', {
                mac: modem.mac_address,
                cmts_ip: modem.cmts_ip,
                fiber_node: modem.fiber_node,
                ofdma_ifindex: modem.ofdma_ifindex,
                upstream_ifindex: modem.upstream_ifindex,
                upstream_interface: modem.upstream_interface,
            });

            // ── Always enrich from /api/modems/{mac} first ──────────────
            // The bulk CMTS modem list may not include ofdma_ifindex,
            // upstream_interface, or fiber_node. This per-modem call is
            // fast and always returns the complete data.
            let m = modem;
            try {
                // Preserve topology/previously-resolved fiber_node before enrichment
                // (inventory/Redis may return empty fiber_node, wiping the topology value).
                const preFiberNode = m.fiber_node || m.fibernode || '';
                const enrichResp = await fetch(`${API_BASE}/modems/${encodeURIComponent(m.mac_address)}`);
                const enrichData = await enrichResp.json();
                if (enrichData?.status === 'success' && enrichData.modem) {
                    // Merge enriched data monotonically onto both references.
                    this._mergeModemPreservingCmts(m, enrichData.modem);
                    if (!m.fiber_node && preFiberNode) {
                        m.fiber_node = preFiberNode;
                    }
                    if (this.selectedModem?.mac_address === m.mac_address) {
                        this._mergeModemPreservingCmts(this.selectedModem, enrichData.modem);
                        if (!this.selectedModem.fiber_node && preFiberNode) {
                            this.selectedModem.fiber_node = preFiberNode;
                        }
                    }
                    this._fnTrace('prime.enriched_modem', {
                        mac: m.mac_address,
                        fiber_node: m.fiber_node,
                        ofdma_ifindex: m.ofdma_ifindex,
                        upstream_ifindex: m.upstream_ifindex,
                        upstream_interface: m.upstream_interface,
                    });
                }
            } catch (_) {
                // Continue with whatever data we have
                this._fnTrace('prime.enrich_failed', { mac: m.mac_address });
            }

            const cmtsName = m.cmts || m.cmts_hostname || '';
            const cmtsMatch = this.findCmtsMatch(m.cmts_ip, cmtsName);

            const resolvedCmtsIp = m.cmts_ip || cmtsMatch?.ip || '';
            if (!resolvedCmtsIp) return;

            this.fnScanCmts = cmtsMatch || {
                name: cmtsName || resolvedCmtsIp,
                ip: resolvedCmtsIp,
            };
            this.fnScanCmtsIp = resolvedCmtsIp;
            this.fnScanCommunity = this.fnScanCommunity || this.snmpCommunity;
            this.fnScanWriteCommunity = this.fnScanWriteCommunity || this.snmpCommunityRW;
            const selectedModemFn = String(m.fiber_node || m.fibernode || '').trim();
            this.fnScanTopologyBridgeNodeId = selectedModemFn.includes('.') ? selectedModemFn : this.fnScanTopologyBridgeNodeId;

            // ── Instant fill from modem data ────────────────────────────
            // Set scanner fields immediately from already-known modem
            // properties so the UI is populated before any network call.
            const instantIfindex = this._toIfindex(m.ofdma_ifindex);
            const channelDesc = m.upstream_interface || (instantIfindex ? `OFDMA ${instantIfindex}` : '');

            // Helper: inject/update FN + channel into scanner state
            const injectFnAndChannel = () => {
                if (selectedModemFn) {
                    this.fnScanFiberNode = selectedModemFn;
                    this._ensureFiberNodeInScanList(selectedModemFn, instantIfindex, { description: channelDesc });
                }
                if (instantIfindex) {
                    this.fnScanIfindex = instantIfindex;
                    const existCh = this.fnScanChannels.find(c => this._toIfindex(c?.ifindex) === instantIfindex);
                    if (!existCh) {
                        this.fnScanChannels.push({
                            ifindex: instantIfindex,
                            description: channelDesc,
                            mac_domain: selectedModemFn,
                            modem_count: null,
                        });
                    } else if (channelDesc && existCh.description?.match(/^OFDMA \d+$/)) {
                        existCh.description = channelDesc;
                    }
                }
            };

            injectFnAndChannel();
            this._fnTrace('prime.after_instant_fill', {
                fnScanFiberNode: this.fnScanFiberNode,
                fnScanIfindex: this.fnScanIfindex,
                selectedMacs: this.fnScanSelectedModemMacs,
                fnChannels: (this.fnScanChannels || []).length,
                fnNodes: (this.fnScanFiberNodes || []).length,
            });
            // Also seed the selectedModem into the modems list so the
            // modem selector panel shows it immediately, before CMTS
            // inventory refresh populates the full list.
            if (!this.modems.some(row => this.normalizeMacForMatch(row?.mac_address) === this.normalizeMacForMatch(m.mac_address))) {
                this.modems.push({
                    mac_address: m.mac_address,
                    ip_address: m.ip_address || '',
                    status: m.status || 'operational',
                    fiber_node: selectedModemFn,
                    upstream_ifindex: m.upstream_ifindex ?? null,
                    cable_mac: m.cable_mac || '',
                    vendor: m.vendor || 'Unknown',
                    docsis_version: m.docsis_version || '',
                    upstream_interface: m.upstream_interface || '',
                    ofdma_ifindex: m.ofdma_ifindex ?? null,
                    ofdm_enabled: m.ofdm_enabled ?? null,
                    ofdma_enabled: m.ofdma_enabled ?? null,
                    cmts_ip: resolvedCmtsIp,
                });
            }
            this.fnScanUseModemSelector = true;
            this.fnScanSelectedModemMacs = [m.mac_address];
            this.fnConfigCollapsed = false;
            console.log('[primeFnScan] instant fill — FN:', this.fnScanFiberNode, 'ifindex:', this.fnScanIfindex, 'channel:', channelDesc);

            // ── Background enrichment ───────────────────────────────────
            // Load full channel list and topology metadata to refine the
            // dropdowns. These calls may be slow but the scanner is
            // already usable from the instant fill above.
            const savedMacs = [...this.fnScanSelectedModemMacs];
            await this.loadFnScanChannels();

            // loadFnScanChannels replaces fnScanChannels + fnScanFiberNodes
            // wholesale — re-inject the instant-fill data so the UI keeps
            // showing the modem's fiber-node name + channel description.
            injectFnAndChannel();
            // Restore modem selection (loadFnScanChannels may have reset it)
            this.fnScanSelectedModemMacs = savedMacs;
            this._fnTrace('prime.after_load_channels_reinject', {
                fnScanFiberNode: this.fnScanFiberNode,
                fnScanIfindex: this.fnScanIfindex,
                selectedMacs: this.fnScanSelectedModemMacs,
                fnChannels: (this.fnScanChannels || []).length,
                fnNodes: (this.fnScanFiberNodes || []).length,
            });

            await this._enrichFnSelectorTopologyMetadata();
            await this.refreshFnSelectorModems(true);

            if (!this.fnScanFiberNodes || this.fnScanFiberNodes.length === 0) {
                this.fnScanFiberNodes = this._buildFallbackFiberNodesFromModems(this.fnScanCmtsIp);
            }

            // Re-assert selected modem MACs after enrichment (async calls may reset)
            this.fnScanSelectedModemMacs = savedMacs;
            if (m.mac_address && !this.fnScanSelectedModemMacs.includes(m.mac_address)) {
                this.fnScanSelectedModemMacs = [m.mac_address, ...this.fnScanSelectedModemMacs];
            }

            // Refine ifindex with OFDMA discovery if we still don't have one.
            let preferredIfindex = instantIfindex;
            if (!preferredIfindex) {
                preferredIfindex = await this._discoverPreferredOFDMAIfindex(m.mac_address, resolvedCmtsIp);
            }
            const mappedFn = preferredIfindex ? this.fnNameForIfindex(preferredIfindex) : null;
            // Keep modem API fiber_node as authoritative (e.g. FN37).
            // Only fallback to mappedFn when fiber_node is missing.
            if (!this.fnScanFiberNode && mappedFn) {
                this.fnScanFiberNode = mappedFn;
            }
            if (this.fnScanFiberNode) {
                this._ensureFiberNodeInScanList(this.fnScanFiberNode, preferredIfindex, { description: channelDesc });
            }
            if (this.fnScanFiberNode) {
                const fn = (this.fnScanFiberNodes || []).find(f => f.name === this.fnScanFiberNode);
                if (fn && fn.channels && fn.channels.length) {
                    const fnIfs = fn.channels.map(c => this._toIfindex(c?.ifindex)).filter(Boolean);
                    if (preferredIfindex) {
                        // Keep preferred OFDMA ifindex from modem data/discovery.
                        this.fnScanIfindex = preferredIfindex;
                        this.fnScanExtraIfindices = fnIfs.filter(i => i !== preferredIfindex);
                    } else {
                        this.fnScanIfindex = fnIfs[0] || '';
                        this.fnScanExtraIfindices = fnIfs.slice(1);
                    }
                    this.fnScanModemCount = fn.modem_count ?? fn.channels[0].modem_count ?? null;
                } else {
                    this.fnScanExtraIfindices = [];
                    this.fnScanIfindex = preferredIfindex || this.fnScanIfindex || '';
                    this.fnScanModemCount = this.fnScanSelectedModemCount || this.fnScanModemCount || null;
                }
            }

            // Final hard re-assert from modem API values.
            if (selectedModemFn) this.fnScanFiberNode = selectedModemFn;
            if (instantIfindex) this.fnScanIfindex = instantIfindex;
            this._fnTrace('prime.final_state', {
                fnScanFiberNode: this.fnScanFiberNode,
                fnScanIfindex: this.fnScanIfindex,
                selectedMacs: this.fnScanSelectedModemMacs,
                modemCountScope: this.fnScanScopeCount,
            });
        },
        
        async selectModem(modem) {
            const wasMeasurementsView = this.currentView === 'measurements';
            this.selectedModem = modem;
            const _needsEnrich = this.selectedModem && this.selectedModem.mac_address &&
                (!this.selectedModem.ip_address || !this.selectedModem.cmts_ip ||
                 !this.selectedModem.vendor || !this.selectedModem.software_version ||
                 !(this.selectedModem.fiber_node || this.selectedModem.fibernode) ||
                 !this.selectedModem.cable_mac ||
                 this.selectedModem.ofdm_enabled == null || this.selectedModem.ofdma_enabled == null ||
                 this.selectedModem.cpe_ipv4 === undefined || this.selectedModem.cpe_ipv6 === undefined);
            if (_needsEnrich) {
                this.modemDetailLoading = true;
                try {
                    const topologyFiberNode = this.selectedModem.fiber_node || this.selectedModem.fibernode || '';
                    const resp = await fetch(`${API_BASE}/modems/${encodeURIComponent(this.selectedModem.mac_address)}`);
                    const data = await resp.json();
                    if (data?.status === 'success' && data.modem) {
                        this._mergeModemPreservingCmts(this.selectedModem, data.modem);
                        if (!this.selectedModem.fiber_node && topologyFiberNode) {
                            this.selectedModem.fiber_node = topologyFiberNode;
                        }
                    }
                } catch (_) {
                    // Best-effort enrichment only.
                } finally {
                    this.modemDetailLoading = false;
                }
            }
            if (this.currentView === 'fibernode') {
                try {
                    await this.primeFnScanFromSelectedModem(this.selectedModem);
                } catch (_) {
                    // Best-effort handoff only.
                }
            }
            if (this.selectedModem && !this.selectedModem.topology_path && this.selectedModem.fiber_node) {
                try {
                    const pr = await fetch(`${API_BASE}/topology/path?node_id=${encodeURIComponent(this.selectedModem.fiber_node)}`);
                    const pd = await pr.json();
                    if (pd?.status === 'success' && pd.path) {
                        this.selectedModem.topology_path = pd.path;
                    }
                } catch (_) {
                    // Best-effort enrichment only.
                }
            }
            this.modemRefreshStatus = null;
            this.modemRefreshRequestId = null;
            this.modemRefreshError = null;
            this.systemInfo = null;
            this.dsChannels = [];
            this.usChannels = [];
            this.channelStats = null;
            this.channelStatsError = null;
            this.rxmerData = null;
            this.spectrumData = null;
            this.fecData = null;
            this.preEqData = null;
            this.eventLog = [];
            this.selectedMeasurementData = null;
            this.showRawData = false;
            this.expandedPlotJson = [];
            
            // Reset upstream interfaces
            this.upstreamInterfaces = { loading: false, scqamChannels: [], ofdmaChannels: [] };
            this.utscConfig.rfPortIfindex = null;
            this.usRxmerConfig.ofdmaIfindex = null;
            
            this.currentView = 'modems';
            
            // Stop enrichment on agent — free up agent for per-modem diagnostics
            if (this.isEnriching) {
                this.stopEnrichment();
            }
            
            // Do not auto-trigger channel stats on modem open.
            // On some deployments this call can run >60s and block other API
            // requests (including upstream interface/RF port discovery).
            // Keep channel stats user-driven via explicit action.

            // Always start RF-port / upstream ifIndex discovery on modem select.
            // This is a lightweight per-modem call (not a CMTS-wide walk), so it
            // won't block the agent. Results are ready by the time user opens
            // Measurements tab.
            if (this.selectedModem?.cmts_ip) {
                console.log('[selectModem] starting loadUpstreamInterfaces for', this.selectedModem.mac_address);
                this.loadUpstreamInterfaces();
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

        async requestInventoryRefresh() {
            if (!this.selectedModem) return;
            await this.requestInventoryRefreshForModem(this.selectedModem, { trackStatus: true });
        },

        async requestInventoryRefreshForModem(modem, opts = {}) {
            if (!modem) return false;
            const trackStatus = opts.trackStatus !== false;
            const mac = modem.mac_address;
            const cmts = modem.cmts || modem.cmts_ip;
            if (!cmts) {
                this.$toast?.warning('Cannot refresh modem: CMTS is unknown');
                return false;
            }
            try {
                const resp = await fetch(`${API_BASE}/modems/${encodeURIComponent(mac)}/refresh`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ cmts }),
                });
                const data = await resp.json();
                if (data.status === 'success') {
                    if (trackStatus && this.selectedModem?.mac_address === mac) {
                        this.modemRefreshRequestId = data.request_id;
                        this.modemRefreshStatus = 'queued';
                        this.modemRefreshError = null;
                        this._pollRefreshStatus(mac);
                    }
                    this.$toast?.info(`Refresh queued for ${mac}`);
                    return true;
                }
                if (trackStatus && this.selectedModem?.mac_address === mac) {
                    this.modemRefreshStatus = 'failed';
                    this.modemRefreshError = data.message || 'Failed to queue refresh';
                }
                this.$toast?.error(data.message || `Failed to queue refresh for ${mac}`);
                return false;
            } catch (e) {
                console.warn('Refresh request failed:', e);
                if (trackStatus && this.selectedModem?.mac_address === mac) {
                    this.modemRefreshStatus = 'failed';
                    this.modemRefreshError = e?.message || 'Request failed';
                }
                this.$toast?.error(`Refresh request failed for ${mac}`);
                return false;
            }
        },
        async _pollRefreshStatus(mac) {
            const maxAttempts = 30;
            for (let i = 0; i < maxAttempts; i++) {
                await new Promise(r => setTimeout(r, 3000));
                if (this.selectedModem?.mac_address !== mac) return;
                try {
                    const resp = await fetch(`${API_BASE}/modems/${encodeURIComponent(mac)}/refresh/status`);
                    const data = await resp.json();
                    const req = data.refresh || data.request;
                    if (!req) return;
                    this.modemRefreshStatus = req.status;
                    this.modemRefreshError = req.error_text || null;
                    if (req.status === 'completed') {
                        // Pull updated modem from MySQL fallback and refresh panel
                        try {
                            const mr = await fetch(`${API_BASE}/modems/${encodeURIComponent(mac)}`);
                            const md = await mr.json();
                            if (md.status === 'success' && md.modem) {
                                this._mergeModemPreservingCmts(this.selectedModem, md.modem);
                            }
                        } catch(_) {}
                        return;
                    }
                    if (req.status === 'failed') return;
                } catch (e) {
                    console.warn('Refresh status poll failed:', e);
                    this.modemRefreshStatus = 'failed';
                    this.modemRefreshError = e?.message || 'Poll failed';
                    return;
                }
            }
            this.modemRefreshStatus = 'failed';
            this.modemRefreshError = 'Timed out waiting for refresh completion';
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

            const resumeEnrichPolling = this.isEnriching;
            if (this._enrichPollTimer) {
                clearTimeout(this._enrichPollTimer);
                this._enrichPollTimer = null;
            }
            this.channelStatsLoading = true;
            this._startChannelStatsProgress();
            
            try {
                // Use PyPNM API for channel stats - correct URL
                const response = await fetch(`${API_BASE}/pypnm/channel-stats/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        modem_ip: this.selectedModem.ip_address,
                        community: this.snmpCommunityModem || 'private',
                        cmts_ip: this.selectedModem.cmts_ip,
                        cmts_community: this.selectedModem.cmts_community || this.snmpCommunity,
                        // Full CMTS stats: button-driven so latency is acceptable.
                        // Needed for OFDM Stats tab (IUC codewords, profile speed, partial reason).
                        cmts_stats: true,
                        // Reuse known registration index when available to skip MAC-table walk.
                        cm_index: this.selectedModem.cm_index || null,
                    })
                });

                this._setChannelStatsProgressPhase('decode');
                if (!response.ok) {
                    const errorPayload = await response.json().catch(() => ({}));
                    throw new Error(
                        errorPayload.error || errorPayload.message ||
                        `Channel statistics request failed (HTTP ${response.status})`
                    );
                }

                const data = await response.json();
                this._setChannelStatsProgressPhase('apply');

                // Explicit failure with no usable data — show error and stop.
                if (data.success === false && !data.downstream && !data.upstream && !data.ofdm_stats) {
                    this.channelStatsError = data.error || 'SNMP failed — modem unreachable or not responding';
                    this._stopChannelStatsProgress(null, true);
                    return;
                }
                this.channelStatsError = null;

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
                    
                    // Pre-load PNM interface ifindices from channel-stats so
                    // UTSC / RxMER don't need a separate discovery step.
                    if (this.selectedModem) {
                        const ofdmaCh = data.upstream?.ofdma?.channels?.[0];
                        if (ofdmaCh?.index != null && !this.selectedModem.ofdma_ifindex) {
                            this.selectedModem.ofdma_ifindex = ofdmaCh.index;
                            console.log('Pre-loaded ofdma_ifindex from channel-stats:', ofdmaCh.index);
                        }
                        const atdmaCh = data.upstream?.atdma?.channels?.[0];
                        if (atdmaCh?.index != null && !this.selectedModem.upstream_ifindex) {
                            this.selectedModem.upstream_ifindex = atdmaCh.index;
                            console.log('Pre-loaded upstream_ifindex from channel-stats:', atdmaCh.index);
                        }
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
                
                // Render charts only after Vue has applied the returned channel data.
                this._setChannelStatsProgressPhase('render');
                await this.$nextTick();
                this.drawDsChannelChart();
                this.drawUsChannelChart();
                
            } catch (error) {
                console.warn('Failed to load channel stats:', error);
                this.channelStatsError = 'Request failed: ' + (error.message || error);
                this._stopChannelStatsProgress(null, true);
            } finally {
                if (!this.channelStatsError) this._stopChannelStatsProgress(this.channelStats);

                // Keep the progress modal visible briefly after completion so users
                // can read step outcomes instead of it disappearing immediately.
                const startedAt = this._csProgressStartedAt || 0;
                const elapsedMs = startedAt ? (Date.now() - startedAt) : 0;
                const minTotalVisibleMs = 2600;
                const postCompleteHoldMs = 1200;
                const extraWaitMs = Math.max(postCompleteHoldMs, minTotalVisibleMs - elapsedMs, 0);
                if (extraWaitMs > 0) {
                    await new Promise(resolve => setTimeout(resolve, extraWaitMs));
                }

                this.channelStatsLoading = false;
                if (resumeEnrichPolling && this.isEnriching && !this._enrichPollTimer) {
                    this._scheduleEnrichPoll();
                }
            }
        },
        
        _startChannelStatsProgress() {
            if (this._csProgressTimer) {
                clearInterval(this._csProgressTimer);
            }
            this._csProgressStartedAt = Date.now();
            this.channelStatsProgress = {
                pct: 0,
                eta: '0s elapsed',
                elapsedSeconds: 0,
                indeterminate: true,
                steps: [
                    { id: 'request', label: 'Collecting modem and CMTS channel data', status: 'active' },
                    { id: 'decode', label: 'Receiving response', status: 'pending' },
                    { id: 'apply', label: 'Applying channel information', status: 'pending' },
                    { id: 'render', label: 'Updating charts', status: 'pending' },
                ],
            };

            this._csProgressTimer = setInterval(() => {
                const elapsedSeconds = Math.max(
                    0,
                    Math.floor((Date.now() - this._csProgressStartedAt) / 1000)
                );
                this.channelStatsProgress = {
                    ...this.channelStatsProgress,
                    elapsedSeconds,
                    eta: `${elapsedSeconds}s elapsed`,
                };
            }, 1000);
        },

        _setChannelStatsProgressPhase(phaseId) {
            const activeIndex = (this.channelStatsProgress.steps || [])
                .findIndex(step => step.id === phaseId);
            if (activeIndex < 0) return;

            const elapsedSeconds = Math.max(
                0,
                Math.floor((Date.now() - (this._csProgressStartedAt || Date.now())) / 1000)
            );
            this.channelStatsProgress = {
                ...this.channelStatsProgress,
                pct: 0,
                eta: `${elapsedSeconds}s elapsed`,
                elapsedSeconds,
                indeterminate: true,
                steps: this.channelStatsProgress.steps.map((step, index) => ({
                    ...step,
                    status: index < activeIndex ? 'done' : index === activeIndex ? 'active' : 'pending',
                })),
            };
        },

        _stopChannelStatsProgress(data, failed = false) {
            if (this._csProgressTimer) {
                clearInterval(this._csProgressTimer);
                this._csProgressTimer = null;
            }

            const apiPartial = !!(data && (data.success === false || Number(data.status) !== 0));
            const errorText = String(data?.error || '').toLowerCase();
            const hasTimeoutHint = errorText.includes('timeout') || errorText.includes('timed out');

            const dsOfdmChannels = data?.downstream?.ofdm?.channels || [];
            const usOfdmaChannels = data?.upstream?.ofdma?.channels || [];
            const hasDsAuthoritativeGap = dsOfdmChannels.some(ch => {
                const hasProfiles = Array.isArray(ch?.profiles) && ch.profiles.length > 0;
                return hasProfiles && ch?.current_profile == null;
            });
            const hasUsAuthoritativeGap = usOfdmaChannels.some(ch => {
                const hasAnyIucData = (Array.isArray(ch?.active_iucs) && ch.active_iucs.length > 0) ||
                                      (Array.isArray(ch?.iuc_stats) && ch.iuc_stats.length > 0);
                return hasAnyIucData && ch?.current_iuc == null;
            });
            const hasAuthoritativeGap = hasDsAuthoritativeGap || hasUsAuthoritativeGap;

            // Derive real per-step outcomes from the response data
            const steps = (this.channelStatsProgress.steps || []).map(s => {
                const label = s.label.replace('...', '');
                if (failed) return { ...s, label, status: 'error' };
                if (!data)  return { ...s, label, status: 'done' };

                let status = 'done';
                let note = '';
                switch (s.id) {
                    case 'connect': {
                        // Modem responded if we have ANY channel data
                        const hasAny = (data.downstream?.scqam?.count > 0 ||
                                        data.downstream?.ofdm?.count > 0 ||
                                        data.upstream?.atdma?.count > 0 ||
                                        data.upstream?.ofdma?.count > 0);
                        status = hasAny ? 'done' : (hasTimeoutHint ? 'error' : 'warn');
                        if (!hasAny) note = ' (no channels)';
                        break;
                    }
                    case 'walk': {
                        const dsOk  = (data.downstream?.scqam?.count > 0 || data.downstream?.ofdm?.count > 0);
                        const usOk  = (data.upstream?.atdma?.count > 0  || data.upstream?.ofdma?.count > 0);
                        if (!dsOk && !usOk) { status = 'error'; note = ' (no channels)'; }
                        else if (!dsOk || !usOk) { status = 'warn'; note = !dsOk ? ' (DS missing)' : ' (US missing)'; }
                        else if (apiPartial) { status = 'warn'; note = hasTimeoutHint ? ' (partial: timeout)' : ' (partial)'; }
                        break;
                    }
                    case 'cmts': {
                        // CMTS enrichment: check if IUC or RxMER were injected
                        const ofdmaChs = data.upstream?.ofdma?.channels || [];
                        const dsProfs  = (data.ofdm_stats?.ds_profiles || []);
                        const hasIuc   = ofdmaChs.some(c => c.current_iuc != null);
                        const hasRxMer = ofdmaChs.some(c => c.rx_mer != null && c.rx_mer > 0);
                        const hasDs    = dsProfs.some(p => p.profiles?.some(pr => pr.full_channel_speed_bps != null));
                        if (!hasIuc && !hasRxMer && !hasDs) { status = 'warn'; note = ' (no CMTS data)'; }
                        else if (hasAuthoritativeGap) { status = 'warn'; note = ' (assigned/current mismatch)'; }
                        else if (apiPartial) { status = 'warn'; note = hasTimeoutHint ? ' (partial: timeout)' : ' (partial)'; }
                        break;
                    }
                    case 'fiber': {
                        if (!data.fiber_node) { status = 'warn'; note = ' (not resolved)'; }
                        break;
                    }
                    case 'parse':
                    default:
                        status = apiPartial ? 'warn' : 'done';
                        if (apiPartial) note = hasTimeoutHint ? ' (partial: timeout)' : ' (partial)';
                        break;
                }
                return { ...s, label: label + note, status };
            });

            const anyError = steps.some(s => s.status === 'error');
            const anyWarn  = steps.some(s => s.status === 'warn');
            const elapsedSeconds = Math.max(
                0,
                Math.round((Date.now() - (this._csProgressStartedAt || Date.now())) / 1000)
            );
            const outcome = anyError
                ? 'Completed with errors'
                : anyWarn
                    ? 'Completed with warnings'
                    : 'Done';
            this.channelStatsProgress = {
                pct: 100,
                eta: `${outcome} · ${elapsedSeconds}s elapsed`,
                elapsedSeconds,
                indeterminate: false,
                steps,
            };
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

            const m = this.selectedModem;

            // Fast path: enrichment already provided ofdma_ifindex / upstream_ifindex.
            // Populate the critical selectors immediately without an SNMP round-trip.
            // The full channel-list fetch runs in the background to fill dropdowns.
            const hasOfdma   = m.ofdma_ifindex != null;
            const hasUpstream = m.upstream_ifindex != null;

            if (hasOfdma && !this.usRxmerConfig.ofdmaIfindex) {
                this.upstreamInterfaces.ofdmaChannels = [{
                    ifindex:       m.ofdma_ifindex,
                    ofdma_ifindex: m.ofdma_ifindex,
                    description:   m.upstream_interface || `OFDMA ${m.ofdma_ifindex}`,
                    index: 1,
                }];
                this.usRxmerConfig.ofdmaIfindex = m.ofdma_ifindex;
            }
            // Always await full upstream interface discovery for UTSC RF port,
            // because modem enrichment can carry non-authoritative upstream_ifindex.
            await this._loadUpstreamInterfacesFull();
        },

        async _loadUpstreamInterfacesFull() {
            if (!this.selectedModem || !this.selectedModem.cmts_ip) {
                return;
            }

            this.upstreamInterfaces.loading = true;
            try {
                const response = await fetch(`${API_BASE}/pypnm/upstream/interfaces/${this.selectedModem.mac_address}`, {
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
                    // UTSC dropdown: use modem_rf_port directly — it IS the answer.
                    if (result.modem_rf_port && result.modem_rf_port.ifindex) {
                        this.upstreamInterfaces.scqamChannels = [result.modem_rf_port];
                        this.utscConfig.rfPortIfindex = parseInt(result.modem_rf_port.ifindex);
                    } else {
                        this.upstreamInterfaces.scqamChannels = [];
                    }

                    // OFDMA dropdown for US RxMER
                    this.upstreamInterfaces.ofdmaChannels = result.ofdma_channels || [];
                    if (this.upstreamInterfaces.ofdmaChannels.length > 0 && !this.usRxmerConfig.ofdmaIfindex) {
                        this.usRxmerConfig.ofdmaIfindex = this.upstreamInterfaces.ofdmaChannels[0].ifindex;
                    }
                    
                    console.log('UTSC rfPortIfindex:', this.utscConfig.rfPortIfindex);
                    console.log('OFDMA channels:', this.upstreamInterfaces.ofdmaChannels.length);
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
                const response = await fetch(`${API_BASE}/pypnm/upstream/utsc/configure/${this.selectedModem.mac_address}`, {
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
                        community: this.snmpCommunity,
                        write_community: this.snmpCommunityRW
                    })
                });
                
                const result = await response.json();
                if (result.success) {
                    if (result.rf_port_ifindex) {
                        this.utscConfig.rfPortIfindex = parseInt(result.rf_port_ifindex);
                    }
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
            if (!(await this.prepareUiTask('UTSC'))) return;
            const { token, signal } = this._beginUiTask('UTSC');
            
            this.runningUtsc = true;
            this.utscStatus = null;
            
            try {
                // First configure (vendor-aware defaults applied in PyPNM), then start
                const configResult = await this.configureUtsc();
                if (!configResult || !configResult.success) {
                    this.runningUtsc = false;
                    return;
                }
                
                const cfgIndexForStart = this.utscConfig.cfgIndex || 0;
                // cfg_index=0 sent to server — auto-probe by TriggerMode, required for EVO rows 2/3.

                const response = await fetch(`${API_BASE}/pypnm/upstream/utsc/start/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip,
                        rf_port_ifindex: this.utscConfig.rfPortIfindex,
                        cfg_index: cfgIndexForStart,
                        trigger_mode: this.utscConfig.triggerMode || 2,
                        community: this.snmpCommunity,
                        write_community: this.snmpCommunityRW
                    }),
                    signal,
                });
                
                const result = await response.json();
                if (!this._isTaskActive(token)) return;
                if (result.success) {
                    const resolvedCfgIndex = Number.parseInt(result.cfg_index, 10);
                    if (!Number.isInteger(resolvedCfgIndex) || resolvedCfgIndex <= 0) {
                        this.$toast?.error('UTSC start returned no usable config row');
                        this.runningUtsc = false;
                        this._activeTaskLabel = null;
                        return;
                    }
                    this.utscConfig.cfgIndex = resolvedCfgIndex;
                    this.$toast?.success('UTSC test started');
                    // Poll for status
                    this.pollUtscStatus(token);
                } else {
                    this.$toast?.error(result.error || 'Failed to start UTSC');
                    this.runningUtsc = false;
                    this._activeTaskLabel = null;
                }
            } catch (error) {
                if (error?.name === 'AbortError') return;
                console.error('Start UTSC error:', error);
                this.$toast?.error('Failed to start UTSC');
                this.runningUtsc = false;
                this._activeTaskLabel = null;
            }
        },
        
        async stopUtsc() {
            if (!this.selectedModem || !this.selectedModem.cmts_ip || !this.utscConfig.rfPortIfindex) {
                return;
            }
            if (this._utscPollTimer) { clearTimeout(this._utscPollTimer); this._utscPollTimer = null; }
            
            try {
                const response = await fetch(`${API_BASE}/pypnm/upstream/utsc/stop/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip,
                        rf_port_ifindex: this.utscConfig.rfPortIfindex,
                        cfg_index: this.utscConfig.cfgIndex || 1,
                        community: this.snmpCommunity,
                        write_community: this.snmpCommunityRW
                    })
                });
                
                const result = await response.json();
                this.runningUtsc = false;
                if (this._activeTaskLabel === 'UTSC') this._activeTaskLabel = null;
                if (result.success) {
                    this.$toast?.success('UTSC test stopped');
                }
            } catch (error) {
                console.error('Stop UTSC error:', error);
                this.runningUtsc = false;
                if (this._activeTaskLabel === 'UTSC') this._activeTaskLabel = null;
            }
        },
        
        async pollUtscStatus(taskToken) {
            if (!this.runningUtsc || !this._isTaskActive(taskToken)) return;
            
            try {
                const response = await fetch(`${API_BASE}/pypnm/upstream/utsc/status/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip,
                        rf_port_ifindex: this.utscConfig.rfPortIfindex,
                        community: this.snmpCommunity,
                        write_community: this.snmpCommunityRW
                    }),
                    signal: this._currentFetchController?.signal,
                });
                
                const result = await response.json();
                if (!this._isTaskActive(taskToken)) return;
                this.utscStatus = result;
                this.utscLastFilename = result.filename || result.capture_filename || this.utscLastFilename;
                
                if (result.is_ready) {
                    this.runningUtsc = false;
                    this._activeTaskLabel = null;
                    this.$toast?.success('UTSC capture complete - fetching data...');
                    // Auto-fetch spectrum data
                    await this.fetchUtscData();
                } else if (result.is_error) {
                    this.runningUtsc = false;
                    this._activeTaskLabel = null;
                    this.$toast?.error('UTSC test failed');
                } else if (result.is_busy) {
                    // Continue polling
                    this._utscPollTimer = setTimeout(() => this.pollUtscStatus(taskToken), 2000);
                }
            } catch (error) {
                if (error?.name === 'AbortError') return;
                console.error('Poll UTSC status error:', error);
                this.runningUtsc = false;
                this._activeTaskLabel = null;
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
            if (!(await this.prepareUiTask('US RxMER'))) return;
            const { token } = this._beginUiTask('US RxMER');
            
            this.runningUsRxmer = true;
            this.usRxmerStatus = null;
            this.usRxmerCaptures = [];
            this.usRxmerCaptureIndex = 0;
            this.usRxmerCaptureTotal = this.usRxmerConfig.numCaptures;

            // Compare mode: force 1 capture, pre_eq=true
            if (this.comparePreEqMode) {
                const macClean = this.selectedModem.mac_address.replace(/:/g, '');
                this.usRxmerFilenameOn  = `usrxmer_${macClean}_preeqon`;
                this.usRxmerFilenameOff = `usrxmer_${macClean}_preeqoff`;
                this.usRxmerComparisonImage = null;
                this.usRxmerAnalysis        = null;
                this.usRxmerCaptureTotal = 1;
                this.usRxmerComparePhase = 1;
                this.usRxmerConfig.preEq = true;
                this.$toast?.info('Compare mode: capturing Pre-EQ ON (1/2)...');
            }
            this.usRxmerDisplayIndex = 0;
            this.usRxmerPreloadedImage = null;
            
            await this.runUsRxmerCapture(token);
        },
        
        async runUsRxmerCapture(taskToken) {
            if (!this._isTaskActive(taskToken)) return;
            if (this.usRxmerCaptureIndex >= this.usRxmerCaptureTotal) {
                this.runningUsRxmer = false;
                this._activeTaskLabel = null;
                this.$toast?.success(`All ${this.usRxmerCaptureTotal} captures complete`);
                return;
            }
            
            const captureNum = this.usRxmerCaptureIndex + 1;
            this.usRxmerStatus = { meas_status_name: `Starting capture ${captureNum}/${this.usRxmerCaptureTotal}`, is_busy: true };
            this.usRxmerPollStart = Date.now();
            
            try {
                const response = await fetch(`${API_BASE}/pypnm/cmts/ofdma/rxmer/start/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip,
                        ofdma_ifindex: this.usRxmerConfig.ofdmaIfindex,
                        community: this.snmpCommunity,
                        write_community: this.snmpCommunityRW,
                        pre_eq: this.usRxmerConfig.preEq,
                        filename: this.comparePreEqMode
                            ? (this.usRxmerComparePhase === 1 ? this.usRxmerFilenameOn : this.usRxmerFilenameOff)
                            : undefined
                    }),
                    signal: this._currentFetchController?.signal,
                });
                
                const result = await response.json();
                if (!this._isTaskActive(taskToken)) return;
                if (result.success) {
                    this.pollUsRxmerStatus(taskToken);
                } else {
                    this.$toast?.error(result.error || 'Failed to start US RxMER');
                    this.runningUsRxmer = false;
                    this._activeTaskLabel = null;
                }
            } catch (error) {
                if (error?.name === 'AbortError') return;
                this.$toast?.error('Failed to start US RxMER');
                this.runningUsRxmer = false;
                this._activeTaskLabel = null;
            }
        },
        
        async pollUsRxmerStatus(taskToken) {
            if (!this.runningUsRxmer || !this._isTaskActive(taskToken)) return;
            
            try {
                const response = await fetch(`${API_BASE}/pypnm/cmts/ofdma/rxmer/status/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip,
                        ofdma_ifindex: this.usRxmerConfig.ofdmaIfindex,
                        community: this.snmpCommunity,
                        write_community: this.snmpCommunityRW
                    }),
                    signal: this._currentFetchController?.signal,
                });
                
                const result = await response.json();
                if (!this._isTaskActive(taskToken)) return;
                const captureNum = this.usRxmerCaptureIndex + 1;
                this.usRxmerStatus = {
                    ...result,
                    meas_status_name: `${result.meas_status_name || 'Polling'} (${captureNum}/${this.usRxmerCaptureTotal})`
                };
                
                if (result.is_ready) {
                    await this.fetchUsRxmerData(taskToken);
                    if (!this._isTaskActive(taskToken)) return;
                    this.usRxmerCaptureIndex++;
                    // Continue to next capture
                    await this.runUsRxmerCapture(taskToken);
                } else if (result.is_error) {
                    this.runningUsRxmer = false;
                    this._activeTaskLabel = null;
                    this.$toast?.error(`US RxMER capture ${captureNum} failed`);
                } else if (Date.now() - (this.usRxmerPollStart || 0) > 60000) {
                    this.runningUsRxmer = false;
                    this._activeTaskLabel = null;
                    this.$toast?.error(`US RxMER capture ${captureNum} timed out`);
                } else {
                    // Keep polling for BUSY, INACTIVE (Cisco transitions through
                    // INACTIVE briefly before going BUSY/SAMPLE_READY), or unknown
                    this._usRxmerPollTimer = setTimeout(() => this.pollUsRxmerStatus(taskToken), 2000);
                }
            } catch (error) {
                if (error?.name === 'AbortError') return;
                this.runningUsRxmer = false;
                this._activeTaskLabel = null;
            }
        },
        
        async fetchUtscData() {
            if (!this.selectedModem || !this.selectedModem.cmts_ip) {
                return;
            }
            
            try {
                const response = await fetch(`${API_BASE}/pypnm/upstream/utsc/data/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip,
                        rf_port_ifindex: this.utscConfig.rfPortIfindex,
                        filename: this.utscLastFilename,
                        community: this.snmpCommunity,
                        write_community: this.snmpCommunityRW,
                        include_plot: true  // Single-shot: include matplotlib plot
                    })
                });
                
                const result = await response.json();
                
                if (result.success && result.data) {
                    this.utscLastFilename = result.data.filename || this.utscLastFilename;
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
        
        async fetchUsRxmerData(taskToken) {
            if (!this.selectedModem || !this.selectedModem.cmts_ip) return;
            
            try {
                const response = await fetch(`${API_BASE}/pypnm/cmts/ofdma/rxmer/data/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip,
                        ofdma_ifindex: this.usRxmerConfig.ofdmaIfindex,
                        community: this.snmpCommunity,
                        write_community: this.snmpCommunityRW
                    }),
                    signal: this._currentFetchController?.signal,
                });
                
                const result = await response.json();
                if (!this._isTaskActive(taskToken)) return;
                
                if (result.success && (result.rxmer_data || result.image_data)) {
                    const capture = {
                        index: this.usRxmerCaptureIndex + 1,
                        image_data: result.image_data || null,
                        rxmer_data: result.rxmer_data || null,
                        timestamp: new Date().toLocaleTimeString(),
                        status: 'complete'
                    };
                    this.usRxmerCaptures.push(capture);
                    this.usRxmerSpectrumData = result.image_data;
                    this.usRxmerDisplayIndex = this.usRxmerCaptures.length - 1;
                    this.$nextTick(() => this.renderUsRxmerChart());

                    // Compare mode: after phase 1, kick off phase 2
                    if (this.comparePreEqMode && this.usRxmerComparePhase === 1) {
                        this.usRxmerComparePhase = 2;
                        this.usRxmerConfig.preEq = false;
                        this.usRxmerCaptureIndex = 0;
                        this.usRxmerCaptureTotal = 1;
                        this.$toast?.info('Compare mode: capturing Pre-EQ OFF (2/2)...');
                        await this.runUsRxmerCapture(taskToken);
                        return;
                    }

                    // Compare mode: after phase 2, fetch comparison
                    if (this.comparePreEqMode && this.usRxmerComparePhase === 2) {
                        this.usRxmerComparePhase = 3;
                        this.$toast?.info('Running comparison analysis...');
                        await this.fetchUsRxmerComparison();
                        return;
                    }
                } else {
                    this.usRxmerCaptures.push({
                        index: this.usRxmerCaptureIndex + 1,
                        image_data: null,
                        timestamp: new Date().toLocaleTimeString(),
                        status: 'error: ' + (result.error || 'unknown')
                    });
                }
            } catch (error) {
                if (error?.name === 'AbortError') return;
                this.usRxmerCaptures.push({
                    index: this.usRxmerCaptureIndex + 1,
                    image_data: null,
                    timestamp: new Date().toLocaleTimeString(),
                    status: 'error: ' + error.message
                });
            }
        },
        
        showUsRxmerCapture(idx) {
            const capture = this.usRxmerCaptures[idx];
            if (idx >= 0 && idx < this.usRxmerCaptures.length && (capture?.rxmer_data || capture?.image_data)) {
                this.usRxmerDisplayIndex = idx;
                this.usRxmerSpectrumData = capture.image_data || null;
                this.showUsRxmerJson = false;
                this.$nextTick(() => this.renderUsRxmerChart());
            }
        },

        async fetchUsRxmerComparison() {
            if (!this.selectedModem || !this.usRxmerFilenameOn || !this.usRxmerFilenameOff) return;
            try {
                const response = await fetch(`${API_BASE}/pypnm/cmts/ofdma/rxmer/comparison/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        filename_preeq_on:  this.usRxmerFilenameOn,
                        filename_preeq_off: this.usRxmerFilenameOff,
                        tftp_path: '/var/lib/tftpboot'
                    })
                });
                const result = await response.json();
                if (result.success) {
                    this.usRxmerComparisonImage = result.image_data;
                    this.usRxmerAnalysis        = result.analysis;
                    this.$nextTick(() => this.renderUsRxmerComparisonChart());
                    this.usRxmerComparePhase = 0;
                    const assessment = result.analysis?.modem_assessments?.[0]?.preeq_assessment || result.analysis?.modem_assessments?.[0]?.assessment || 'N/A';
                    this.$toast?.success(`Comparison done — Assessment: ${assessment}`);
                } else {
                    this.$toast?.error(result.error || 'Comparison failed');
                    this.usRxmerComparePhase = 0;
                }
            } catch (error) {
                this.$toast?.error('Comparison request failed');
                this.usRxmerComparePhase = 0;
            }
        },

        async runFiberNodeAnalysis() {
            if (!this.fiberNodeCaptures.length) {
                this.$toast?.error('Add at least one capture to the fiber node list');
                return;
            }
            this.runningFiberNode = true;
            try {
                const response = await fetch(`${API_BASE}/pypnm/cmts/ofdma/rxmer/fibernode`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ captures: this.fiberNodeCaptures, tftp_path: '/var/lib/tftpboot' })
                });
                const result = await response.json();
                if (result.success) {
                    this.fiberNodeImage    = result.image_data;
                    this.fiberNodeAnalysis = result.analysis;
                    this.$nextTick(() => this.renderManualFiberNodeChart());
                    const s = result.analysis?.summary;
                    this.$toast?.success(`Done — ${s?.num_modems} modems, ${s?.pct_network_impaired?.toFixed(1)}% network-impaired`);
                } else {
                    this.$toast?.error(result.error || 'Fiber node analysis failed');
                }
            } catch (error) {
                this.$toast?.error('Fiber node analysis request failed');
            } finally {
                this.runningFiberNode = false;
            }
        },

        addCurrentToFiberNode() {
            const capture = this.usRxmerCaptures[this.usRxmerDisplayIndex];
            if (!capture || !capture.rxmer_data) return;
            this.addToFiberNode({
                cm_mac_address: this.selectedModem ? this.selectedModem.mac_address : '',
                filename:       capture.rxmer_data.filename || '',
                preeq_enabled:  capture.rxmer_data.preeq_enabled !== undefined ? capture.rxmer_data.preeq_enabled : true,
            });
        },

        addToFiberNode(capture) {
            const exists = this.fiberNodeCaptures.find(
                c => c.cm_mac_address === capture.cm_mac_address && c.filename === capture.filename
            );
            if (!exists) {
                this.fiberNodeCaptures.push(capture);
                this.$toast?.success(`Added ${capture.cm_mac_address} (${capture.preeq_enabled ? 'Pre-EQ ON' : 'OFF'}) to fiber node list`);
            } else {
                this.$toast?.info('Capture already in fiber node list');
            }
        },

        removeFromFiberNode(idx) {
            this.fiberNodeCaptures.splice(idx, 1);
        },

        assessmentBadgeClass(assessment) {
            const map = {
                'in-home':      'badge bg-danger',
                'network':      'badge bg-warning text-dark',
                'clean':        'badge bg-success',
                'outlier':      'badge bg-danger',
                'inconclusive': 'badge bg-secondary',
            };
            return map[assessment] || 'badge bg-secondary';
        },

        // ---- Fiber Node Service Group scan (separate menu) ----
        async selectFnScanCmts(cmts) {
            const resolved = this.findCmtsMatch(cmts?.ip, cmts?.hostname || cmts?.name || cmts?.cmts || '') || cmts;
            this.fnScanCmts           = resolved;
            this.fnScanCmtsIp         = resolved?.ip || cmts?.ip || '';
            this.fnScanCommunity      = resolved?.community || cmts?.community || this.snmpCommunity;
            this.fnScanWriteCommunity = resolved?.community_rw || cmts?.community_rw || this.snmpCommunityRW;
            this.fnScanIfindex        = '';
            this.fnScanFiberNode      = '';
            this.fnScanResult         = null;
            this.fnScanImage          = null;
            this.fnScanPlantAssessment = null;
            this.fnScanTapPlotImage   = null;
            this.fnScanTapProfile     = null;
            this.fnImpulseResult       = null;
            this._destroyChartSurface('surface-bulk-fn-rxmer');
            this._destroyChartSurface('surface-fn-tap-profile');
            this._destroyFiberNodeImpulseCharts();
            this.fnScanChannels       = [];
            this.fnScanFiberNodes     = [];
            this.clearFnScanSelectorFilters();
            this.fnScanSelectedModemMacs = [];
            this.fnScanExpectedServingGroup = '';
            this.modems              = [];
            await this.loadFnScanChannels();
            this.refreshFnSelectorModems(true);
        },

        async loadFnScanChannels(refresh = false) {
            if (!this.fnScanCmtsIp || !this.fnScanCommunity) return;
            this.fnScanChannelsLoading = true;
            try {
                const r = await fetch(`${API_BASE}/pypnm/cmts/ofdma/channels`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ cmts_ip: this.fnScanCmtsIp, community: this.fnScanCommunity, refresh })
                });
                const d = await r.json();
                if (d.success) {
                    this.fnScanChannels   = d.channels   || [];
                    this.fnScanFiberNodes = d.fiber_nodes || [];
                    this.fnScanChannelsCached = d._cached || false;
                    this._fnTrace('load_channels.success', {
                        cmts_ip: this.fnScanCmtsIp,
                        channels: this.fnScanChannels.length,
                        fiber_nodes: this.fnScanFiberNodes.length,
                        selected_fn: this.fnScanFiberNode,
                        selected_ifindex: this.fnScanIfindex,
                        cached: d._cached || false,
                    });
                } else {
                    this.$toast?.error(d.error || 'Could not load OFDMA channels');
                    this._fnTrace('load_channels.error', { error: d.error || 'Could not load OFDMA channels' });
                }
            } catch (e) {
                this.$toast?.error('Channel load failed');
                this._fnTrace('load_channels.exception', { message: e?.message || String(e) });
            } finally {
                this.fnScanChannelsLoading = false;
            }
        },

        async refreshFnScanChannels() {
            await this.loadFnScanChannels(true);
            this.$toast?.success('FiberNode channels refreshed from CMTS');
        },

        selectFnChannel(ch) {
            this.fnScanIfindex = ch.ifindex;
            // Use modem_count from channel data if available (from channel/list)
            this.fnScanModemCount = ch.modem_count ?? null;
            // Only fetch if not already in channel data
            if (this.fnScanModemCount === null) {
                this.loadFnModemCount();
            }
        },

        selectFnFiberNode(fn) {
            this.fnScanFiberNode = fn.name;
            this.fnScanFN2Name = '';
            this.fnScanFN2Ifindex = null;
            this.fnScanFN2Channels = [];
            // Auto-select ALL channels of this fiber node — primary = first, rest = extras
            if (fn.channels && fn.channels.length) {
                this.fnScanIfindex = fn.channels[0].ifindex;
                this.fnScanExtraIfindices = fn.channels.slice(1).map(c => c.ifindex);
                // Use fiber node total (unique modems) rather than first-channel count
                this.fnScanModemCount = fn.modem_count ?? fn.channels[0].modem_count ?? null;
                // Always fetch channel modem MACs to seed selector stubs.
                // Some CMTS cache paths can be partial; this guarantees selector rows.
                this.loadFnModemCount();
            } else {
                this.fnScanExtraIfindices = [];
            }
            // Reset selector because FN context changed.
            this.clearFnScanSelectorFilters();
            this.fnScanSelectedModemMacs = [];
        },

        selectFnFiberNode2(fn) {
            // Pick a second fiber node — add its first channel to extras
            this.fnScanFN2Name = fn.name;
            if (fn.channels && fn.channels.length) {
                const newIfindices = fn.channels.map(c => c.ifindex)
                    .filter(i => i != this.fnScanIfindex && !this.fnScanExtraIfindices.includes(i));
                this.fnScanFN2Ifindex = fn.channels[0].ifindex;
                // Replace any previous FN2 channels with new ones
                const prevFN2Set = new Set(this.fnScanFN2Channels || []);
                this.fnScanExtraIfindices = [
                    ...this.fnScanExtraIfindices.filter(i => !prevFN2Set.has(i)),
                    ...newIfindices
                ];
                this.fnScanFN2Channels = newIfindices;
            }
        },

        removeFnFiberNode2() {
            const prevFN2Set = new Set(this.fnScanFN2Channels || []);
            this.fnScanExtraIfindices = this.fnScanExtraIfindices.filter(i => !prevFN2Set.has(i));
            this.fnScanFN2Name = '';
            this.fnScanFN2Ifindex = null;
            this.fnScanFN2Channels = [];
        },

        fnNameForIfindex(ifidx) {
            // Return the fiber node name that owns this channel ifindex
            for (const fn of this.fnScanFiberNodes) {
                if (fn.channels && fn.channels.some(c => c.ifindex == ifidx)) {
                    return fn.name;
                }
            }
            return null;
        },

        addFnChannel() {
            // Add the currently selected channel as an extra scan channel
            const ifidx = parseInt(this.fnScanIfindex);
            if (!ifidx) return;
            if (this.fnScanExtraIfindices.includes(ifidx)) return;
            this.fnScanExtraIfindices.push(ifidx);
            // Advance selector to next channel in the fiber node (if available)
            const filtered = this.fnScanFilteredChannels;
            const idx = filtered.findIndex(c => c.ifindex == ifidx);
            if (idx >= 0 && idx + 1 < filtered.length) {
                this.fnScanIfindex = filtered[idx + 1].ifindex;
                this.loadFnModemCount();
            }
        },

        removeFnChannel(ifidx) {
            this.fnScanExtraIfindices = this.fnScanExtraIfindices.filter(i => i !== ifidx);
        },

        fnScanSelectAllVisibleModems() {
            const maxAllowed = this.fnScanMaxSelectableModems;
            const selected = [...(this.fnScanSelectedModemMacs || [])];
            const selectedNorm = new Set(selected.map(m => this.normalizeMacForMatch(m)).filter(Boolean));
            const addable = [];
            for (const modem of (this.fnScanCandidateModems || [])) {
                if (modem._linked_node_mismatch) continue;
                const mac = modem?.mac_address || '';
                const norm = this.normalizeMacForMatch(mac);
                if (!norm || selectedNorm.has(norm)) continue;
                addable.push(mac);
            }
            const slotsLeft = Math.max(0, maxAllowed - selected.length);
            if (slotsLeft <= 0) {
                this.$toast?.warning(`Maximum ${maxAllowed} modems can be selected.`);
                return;
            }
            const toAdd = addable.slice(0, slotsLeft);
            this.fnScanSelectedModemMacs = [...new Set([...selected, ...toAdd])];
            if (addable.length > toAdd.length) {
                this.$toast?.warning(`Maximum ${maxAllowed} modems can be selected.`);
            }
            this._normalizeFnSelectedMacsToCurrentRows();
            const addedMacs = new Set(toAdd.map(mac => this.normalizeMacForMatch(mac)).filter(Boolean));
            const addedRows = (this.fnScanCandidateModems || []).filter(modem => (
                addedMacs.has(this.normalizeMacForMatch(modem?.mac_address))
            ));
            this.queueSelectedModemEnrichment(addedRows, {
                scope: 'Fiber Node selection',
                maxBatch: 20,
                cmts: this.fnScanCmts?.name || this.fnScanCmtsIp,
            });
        },

        fnScanClearSelectedModems() {
            this.fnScanSelectedModemMacs = [];
        },

        fnScanIsMacSelected(mac) {
            const norm = this.normalizeMacForMatch(mac || '');
            if (!norm) return false;
            return (this.fnScanSelectedModemMacs || [])
                .some(m => this.normalizeMacForMatch(m) === norm);
        },

        fnScanToggleModemSelection(mac) {
            const norm = this.normalizeMacForMatch(mac || '');
            if (!norm) return;
            const current = [...(this.fnScanSelectedModemMacs || [])];
            const idx = current.findIndex(m => this.normalizeMacForMatch(m) === norm);
            if (idx >= 0) {
                current.splice(idx, 1);
            } else {
                const maxAllowed = this.fnScanMaxSelectableModems;
                if (current.length >= maxAllowed) {
                    this.$toast?.warning(`Maximum ${maxAllowed} modems can be selected.`);
                    return;
                }
                // Warn when selecting a DOCSIS 3.0 modem (no OFDM/OFDMA support)
                const modem = (this.fnScanCandidateModems || []).find(m => this.normalizeMacForMatch(m.mac_address) === norm);
                if (modem && !this.fnScanModemSupportsUsRxmer(modem)) {
                    this.$toast?.warning('DOCSIS 3.0 modem — no OFDM/OFDMA. Will be skipped during US RxMER scan.');
                }
                current.push(mac);
                this.queueSelectedModemEnrichment([modem || {
                    mac_address: mac,
                    cmts_ip: this.fnScanCmtsIp,
                }], {
                    scope: 'Fiber Node selection',
                    maxBatch: 1,
                    cmts: this.fnScanCmts?.name || this.fnScanCmtsIp,
                });
            }
            this.fnScanSelectedModemMacs = current;
            this._normalizeFnSelectedMacsToCurrentRows();
        },

        fnScanAllVisibleSelected() {
            const vis = (this.fnScanCandidateModems || []).filter(m => !m._linked_node_mismatch);
            if (!vis.length) return false;
            return vis.every(m => this.fnScanIsMacSelected(m.mac_address));
        },

        fnScanModemSupportsUsRxmer(modem) {
            if (!modem) return false;
            if (this.hasPositiveOfdmaEvidence(modem) || this.hasPositiveOfdmEvidence(modem)) return true;
            return this.docsisVersionRank(this.resolveDocsisVersion(modem, 'Unknown')) >= 31;
        },

        async refreshFnSelectorModems(force = false, liveSnmp = false) {
            if (!this.fnScanCmtsIp || this.fnScanSelectorRefreshInFlight) return;
            const now = Date.now();
            if (!force && (now - this.fnScanLastSelectorRefreshAt) < 30000) return;

            this.fnScanSelectorRefreshInFlight = true;
            this.fnScanLastSelectorRefreshAt = now;
            try {
                // Prefer canonical hostname for API lookup. Display name can miss
                // CMTSProvider matching and force partial-cache fallback.
                const cmtsRef = this.fnScanCmts?.hostname || this.fnScanCmts?.name || this.fnScanCmtsIp;
                // FiberNode selector only needs modem inventory fields; deep modem enrichment
                // (vendor/firmware/sysDescr per modem) is too slow on large CMTSes.
                // Only append refresh=true when explicitly requested (liveSnmp) to avoid
                // triggering a full SNMP walk on every fiber node selection.
                const q = `community=${encodeURIComponent(this.fnScanCommunity || this.snmpCommunity)}&limit=${CM_MODEM_LIMIT}&enrich=false&allow_partial=true${liveSnmp ? '&refresh=true' : ''}`;

                let resp = await fetch(`${API_BASE}/cmts/${encodeURIComponent(cmtsRef)}/modems?${q}`);
                if (resp.status === 404) {
                    const cmtsRefLc = String(cmtsRef || '').toLowerCase();
                    if (cmtsRefLc && cmtsRefLc !== String(cmtsRef || '')) {
                        resp = await fetch(`${API_BASE}/cmts/${encodeURIComponent(cmtsRefLc)}/modems?${q}`);
                    }
                }
                if (resp.status === 404) {
                    // Fallback for deployments where CMTS lookup is only exposed via /modems
                    resp = await fetch(`${API_BASE}/modems?cmts=${encodeURIComponent(cmtsRef)}`);
                }

                const data = await resp.json();
                if (data.status !== 'success' || !Array.isArray(data.modems)) return;

                const existingRows = (this.modems || []);
                const existingByMac = new Map();
                for (const row of existingRows) {
                    const k = this.normalizeMacForMatch(row?.mac_address || '');
                    if (!k) continue;
                    existingByMac.set(k, row);
                }

                // Keep only relevant fields used by selector and scan payload generation.
                const selectedMacNorm = this.normalizeMacForMatch(this.selectedModem?.mac_address || '');
                const selectedSnapshot = this.selectedModem ? { ...this.selectedModem } : null;
                const mergedRows = data.modems.map(m => {
                    const existing = existingByMac.get(this.normalizeMacForMatch(m.mac_address || '')) || {};
                    const linkedNodeId = String(m.linked_node_id || existing.linked_node_id || '').trim();
                    const derived = this._deriveTopologyLevels(linkedNodeId);
                    const merged = this._mergeModemPreservingCmts({ ...existing }, m);
                    return {
                        ...merged,
                        mac_address: m.mac_address || existing.mac_address || '',
                        ip_address: m.ip_address || existing.ip_address || '',
                        status: m.status || existing.status || '',
                        fiber_node: m.fiber_node || existing.fiber_node || '',
                        cable_mac: m.cable_mac || existing.cable_mac || '',
                        vendor: merged.vendor || 'Unknown',
                        partial_service: this.normalizePartialService(m.partial_service ?? existing.partial_service),
                        partial_service_downstream: m.partial_service_downstream ?? existing.partial_service_downstream ?? null,
                        partial_service_upstream: m.partial_service_upstream ?? existing.partial_service_upstream ?? null,
                        partial_service_state: m.partial_service_state ?? existing.partial_service_state ?? null,
                        cmts_ip: m.cmts_ip || data.cmts_ip || existing.cmts_ip || this.fnScanCmtsIp,
                        linked_node_id: linkedNodeId,
                        lat: m.lat ?? existing.lat ?? null,
                        lon: m.lon ?? existing.lon ?? null,
                        topology_group_amplifier: derived.topology_group_amplifier || '',
                        topology_end_amplifier: derived.topology_end_amplifier || '',
                        topology_tap: derived.topology_tap || '',
                        topology_node_id: derived.topology_node_id || '',
                        topology_segment: existing.topology_segment || '',
                    };
                });

                // Keep channel stubs that are not present in refresh payload.
                // This prevents selector list from collapsing when backend returns
                // a partial/tiny modem set during cache transitions.
                const mergedNorm = new Set(
                    mergedRows
                        .map(r => this.normalizeMacForMatch(r.mac_address || ''))
                        .filter(Boolean)
                );
                const preservedStubs = existingRows.filter(r => {
                    if (!r || !r._channel_stub) return false;
                    const norm = this.normalizeMacForMatch(r.mac_address || '');
                    return !!norm && !mergedNorm.has(norm);
                });
                this.modems = [...mergedRows, ...preservedStubs];

                // Keep selected modem as source-of-truth when it has richer fields.
                if (selectedMacNorm && selectedSnapshot) {
                    const idx = this.modems.findIndex(r => this.normalizeMacForMatch(r.mac_address || '') === selectedMacNorm);
                    if (idx >= 0) {
                        // Selected modem is authoritative for FN/OFDMA-related fields.
                        // Keep selected values when present, and only use selector row as fallback.
                        const merged = this._mergeModemPreservingCmts(
                            { ...this.modems[idx] },
                            selectedSnapshot,
                        );
                        this.modems[idx] = merged;
                        // Keep object identity for bindings that hold selectedModem reference.
                        this._mergeModemPreservingCmts(this.selectedModem, merged);
                    }
                }
                await this._enrichFnSelectorTopologyMetadata();
                this._normalizeFnSelectedMacsToCurrentRows();
                this._fnTrace('selector.refresh', {
                    cmts: cmtsRef,
                    modems_loaded: this.modems.length,
                    refresh_rows: mergedRows.length,
                    preserved_stubs: preservedStubs.length,
                    selected_fn: this.fnScanFiberNode,
                    selected_ifindex: this.fnScanIfindex,
                    selected_macs: this.fnScanSelectedModemMacs,
                    base_count: this.fnScanBaseModems.length,
                    filtered_count: this.fnScanFilteredModems.length,
                    cached: data.cached,
                    partial: data.partial,
                    source: data.source || data.agent_id || 'unknown',
                });
            } catch (_) {
                // Silent in selector refresh path
                this._fnTrace('selector.refresh_failed', { cmts: this.fnScanCmtsIp });
            } finally {
                this.fnScanSelectorRefreshInFlight = false;
            }
        },

        async loadFnModemCount(forceSnmp = false) {
            if (!this.fnScanCmtsIp || !this.fnScanCommunity || !this.fnScanIfindex) return;
            this.fnScanModemCountLoading = true;
            try {
                const payload = {
                    cmts_ip:       this.fnScanCmtsIp,
                    community:     this.fnScanCommunity,
                    ofdma_ifindex: parseInt(this.fnScanIfindex),
                    max_modems:    500,
                };
                if (forceSnmp) payload.force_snmp = true;
                const r = await fetch(`${API_BASE}/pypnm/cmts/ofdma/channel/modems`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const d = await r.json();
                if (d.success && Array.isArray(d.modems)) {
                    this.fnScanModemCount = d.modems.length;
                    this.fnScanModemSource = d.source || 'snmp';
                    this.fnScanModemLoadedAt = new Date();

                    // Merge channel modems into this.modems so selector always
                    // has them even if CMTS cache did not return them. Use stubs
                    // for missing MACs, and upgrade partial same-MAC rows when needed.
                    const rows = (this.modems || []);
                    const existing = new Map();
                    for (const m of rows) {
                        const norm = this.normalizeMacForMatch(m.mac_address || '');
                        if (norm) existing.set(norm, m);
                    }

                    const stubs = [];
                    let upgraded = 0;
                    for (const cm of d.modems) {
                        const mac = cm.cm_mac_address || '';
                        const norm = this.normalizeMacForMatch(mac);
                        if (!norm) continue;
                        const current = existing.get(norm);
                        if (current) {
                            // If a same-MAC row exists but has no IP/status context,
                            // mark it as channel-stub so it remains eligible in selector.
                            if (!current._channel_stub && !String(current.ip_address || '').trim()) {
                                current._channel_stub = true;
                                current.status = current.status || 'operational';
                                current.cmts_ip = current.cmts_ip || this.fnScanCmtsIp;
                                current.fiber_node = current.fiber_node || this.fnScanFiberNode || '';
                                current.upstream_ifindex = current.upstream_ifindex ?? this.fnScanIfindex ?? null;
                                upgraded += 1;
                            }
                            continue;
                        }
                        stubs.push({
                            mac_address: mac,
                            ip_address: '',
                            status: 'operational',
                            cmts_ip: this.fnScanCmtsIp,
                            cmts: this.fnScanCmts?.name || '',
                            fiber_node: this.fnScanFiberNode || '',
                            cable_mac: '',
                            upstream_interface: '',
                            upstream_ifindex: this.fnScanIfindex ?? null,
                            vendor: '',
                            docsis_version: '',
                            topology_group_amplifier: '',
                            topology_end_amplifier: '',
                            topology_node_id: String(this.fnScanTopologyBridgeNodeId || ''),
                            _channel_stub: true,
                        });
                    }
                    if (stubs.length) {
                        this.modems = [...rows, ...stubs];
                    } else if (upgraded) {
                        // Force reactivity after in-place upgrades.
                        this.modems = rows.slice();
                    }

                    this._fnTrace('load_modem_count.merge', {
                        channel_mac_count: d.modems.length,
                        stubs_added: stubs.length,
                        rows_upgraded: upgraded,
                        total_rows_after: this.modems.length,
                    });

                    // Reconcile selection format after stubs are merged.
                    this._normalizeFnSelectedMacsToCurrentRows();
                }
            } catch (e) {
                // Silent fail - modem count is optional info
            } finally {
                this.fnScanModemCountLoading = false;
            }
        },

        impulseDirectionStatusLabel(status) {
            return {
                analyzed: 'Retrieved + analyzed',
                captured_analyzed: 'Captured + analyzed',
                missing: 'No current match',
                retrieval_failed: 'Retrieval failed',
                analysis_failed: 'Analysis failed',
                timeout: 'Timed out',
                agent_unavailable: 'Agent unavailable',
                capture_failed: 'Capture failed',
                unavailable: 'Unavailable',
            }[status] || status || 'Unavailable';
        },

        impulseDirectionStatusClass(status) {
            if (['analyzed', 'captured_analyzed'].includes(status)) return 'bg-success';
            if (['retrieval_failed', 'analysis_failed', 'capture_failed', 'timeout'].includes(status)) return 'bg-danger';
            if (status === 'agent_unavailable') return 'bg-warning text-dark';
            return 'bg-secondary';
        },

        _fiberNodeImpulseScopeTargets(includeIp = false) {
            const selected = new Set(
                (this.fnScanSelectedModemMacs || []).map(mac => this.normalizeMacForMatch(mac)).filter(Boolean)
            );
            return (this.fnScanFilteredModems || [])
                .filter(modem => !this.fnScanUseModemSelector || selected.has(this.normalizeMacForMatch(modem.mac_address)))
                .slice(0, Math.max(1, parseInt(this.fnScanMaxModems) || 20))
                .filter(modem => modem.mac_address)
                .map(modem => ({
                    mac_address: modem.mac_address,
                    ...(includeIp ? { ip_address: String(modem.ip_address || '').trim() } : {}),
                }));
        },

        _destroyFiberNodeImpulseCharts() {
            [
                'surface-fn-impulse-ds-frequency',
                'surface-fn-impulse-ds-time',
                'surface-fn-impulse-us-frequency',
                'surface-fn-impulse-us-time',
            ].forEach(key => this._destroyChartSurface(key));
            this.fnImpulseChartAvailability = {
                dsFrequency: false,
                dsImpulse: false,
                usFrequency: false,
                usImpulse: false,
            };
        },

        renderFiberNodeImpulseCharts() {
            this._destroyFiberNodeImpulseCharts();
            const datasets = {
                downstream: { frequency: [], impulse: [] },
                upstream: { frequency: [], impulse: [] },
            };
            let seriesIndex = 0;
            for (const [modemIndex, modem] of (this.fnImpulseResult?.modems || []).entries()) {
                for (const result of (modem?.results || [])) {
                    const direction = result?.direction;
                    if (!datasets[direction]) continue;
                    const channelId = result?.analysis?.channel_id ?? '?';
                    const directionLabel = direction === 'downstream' ? 'DS' : 'US';
                    const label = `Modem ${modemIndex + 1} · ${directionLabel} ch ${channelId}`;
                    const color = this._seriesColor(seriesIndex++);
                    const frequency = result?.chart_data?.frequency_response || {};
                    const impulse = result?.chart_data?.impulse_response || {};
                    const frequencyPoints = this._numericPoints(frequency.frequency_mhz, frequency.magnitude_db);
                    const impulsePoints = this._numericPoints(impulse.delay_us, impulse.relative_db);
                    if (frequencyPoints.length) {
                        datasets[direction].frequency.push({ label, data: frequencyPoints, borderColor: color });
                    }
                    if (impulsePoints.length) {
                        datasets[direction].impulse.push({ label, data: impulsePoints, borderColor: color });
                    }
                }
            }

            this.fnImpulseChartAvailability = {
                dsFrequency: datasets.downstream.frequency.length > 0,
                dsImpulse: datasets.downstream.impulse.length > 0,
                usFrequency: datasets.upstream.frequency.length > 0,
                usImpulse: datasets.upstream.impulse.length > 0,
            };
            const allFrequencyPointSets = [
                ...datasets.downstream.frequency.map(dataset => dataset.data),
                ...datasets.upstream.frequency.map(dataset => dataset.data),
            ];
            const frequencyDbAxis = this._dbAxisPolicy(allFrequencyPointSets);
            const impulseDbAxis = this._dbAxisPolicy([], {
                minimum: -70,
                maximum: 0,
                stepSize: 10,
            });
            const frequencyYTitle = `Magnitude (dB · ${frequencyDbAxis.dbPerDivision} dB/div)`;
            const impulseYTitle = `Relative magnitude (dB · ${impulseDbAxis.dbPerDivision} dB/div)`;
            const downstreamFrequencyAxis = this._frequencyAxisPolicy(
                'downstream',
                datasets.downstream.frequency.map(dataset => dataset.data),
            );
            const upstreamFrequencyAxis = this._frequencyAxisPolicy(
                'upstream',
                datasets.upstream.frequency.map(dataset => dataset.data),
            );
            this.$nextTick(() => {
                this._renderQuantitativeChart(
                    'surface-fn-impulse-ds-frequency', 'fnImpulseDsFrequencyChart', datasets.downstream.frequency,
                    {
                        title: 'Downstream Frequency-response Comparison',
                        xTitle: downstreamFrequencyAxis.title,
                        yTitle: frequencyYTitle,
                        maxPoints: 2000,
                        xScale: downstreamFrequencyAxis.xScale,
                        yScale: frequencyDbAxis.yScale,
                    }
                );
                this._renderQuantitativeChart(
                    'surface-fn-impulse-ds-time', 'fnImpulseDsTimeChart', datasets.downstream.impulse,
                    {
                        title: 'Downstream Detector-windowed Impulse Response',
                        xTitle: 'Delay after main tap (µs)',
                        yTitle: impulseYTitle,
                        maxPoints: 2000,
                        yScale: impulseDbAxis.yScale,
                    }
                );
                this._renderQuantitativeChart(
                    'surface-fn-impulse-us-frequency', 'fnImpulseUsFrequencyChart', datasets.upstream.frequency,
                    {
                        title: 'Upstream Frequency-response Comparison',
                        xTitle: upstreamFrequencyAxis.title,
                        yTitle: frequencyYTitle,
                        maxPoints: 2000,
                        xScale: upstreamFrequencyAxis.xScale,
                        yScale: frequencyDbAxis.yScale,
                    }
                );
                this._renderQuantitativeChart(
                    'surface-fn-impulse-us-time', 'fnImpulseUsTimeChart', datasets.upstream.impulse,
                    {
                        title: 'Upstream Detector-windowed Impulse Response',
                        xTitle: 'Delay after main tap (µs)',
                        yTitle: impulseYTitle,
                        maxPoints: 2000,
                        yScale: impulseDbAxis.yScale,
                    }
                );
            });
        },

        async _runFiberNodeImpulseJob({ targets, source, direction, velocityFactor, token, signal }) {
            const jobId = crypto.randomUUID ? crypto.randomUUID() : `impulse_${Date.now()}_${direction}`;
            this.fnImpulseJobId = jobId;
            this.fnImpulseProgress = {
                total: targets.length,
                completed: 0,
                success_count: 0,
                failure_count: 0,
                direction_attempt_count: 0,
                analyzed_direction_count: 0,
                timeout_count: 0,
                capture_failed_count: 0,
                analysis_failed_count: 0,
                agent_unavailable_count: 0,
                other_failure_count: 0,
                running_count: 0,
                queued_count: targets.length,
                pct: 0,
                state: 'submitting',
                action: `Submitting ${targets.length} modem target${targets.length === 1 ? '' : 's'}`,
                elapsed_s: 0,
                done: false,
            };
            const jobPayload = {
                job_id: jobId,
                targets,
                source,
                direction,
                velocity_factor: velocityFactor,
                topology_date: this.fnScanModemLoadedAt || null,
                fiber_node: this.fnScanFiberNode || null,
                concurrency: 3,
            };

            const startResponse = await fetch(`${API_BASE}/pypnm/impulse-response/fibernode/jobs`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(jobPayload),
                signal,
            });
            const started = await startResponse.json();
            if (!startResponse.ok || !started.started) throw new Error(started.error || 'Could not start bulk analysis');
            const acceptedTargets = Number(started.target_count || targets.length);
            const acceptedConcurrency = Math.min(Number(started.concurrency || 1), acceptedTargets);
            this.fnImpulseProgress = {
                ...this.fnImpulseProgress,
                total: acceptedTargets,
                running_count: acceptedConcurrency,
                queued_count: Math.max(0, acceptedTargets - acceptedConcurrency),
                state: 'running',
                action: `${acceptedTargets} target${acceptedTargets === 1 ? '' : 's'} accepted · up to ${acceptedConcurrency} in parallel`,
            };

            const timeoutBudgetSeconds = Math.max(60, Number(started.timeout_budget_s || 15 * 60));
            const deadline = Date.now() + timeoutBudgetSeconds * 1000;
            let done = false;
            let firstPoll = true;
            while (!done && Date.now() < deadline && this._isTaskActive(token)) {
                if (!firstPoll) await new Promise(resolve => setTimeout(resolve, 350));
                firstPoll = false;
                const progressResponse = await fetch(
                    `${API_BASE}/pypnm/impulse-response/fibernode/jobs/${encodeURIComponent(jobId)}`,
                    { signal }
                );
                const progress = await progressResponse.json();
                if (progress.found) {
                    this.fnImpulseProgress = progress;
                    done = !!progress.done;
                }
            }
            if (!this._isTaskActive(token)) return null;
            if (!done) throw new Error('Bulk impulse-response job timed out');

            const resultResponse = await fetch(
                `${API_BASE}/pypnm/impulse-response/fibernode/jobs/${encodeURIComponent(jobId)}/results`,
                { signal }
            );
            const result = await resultResponse.json();
            if (!resultResponse.ok || !result.found) throw new Error(result.error || 'Bulk result was not found');
            const resultTotal = Number(result.total || acceptedTargets);
            const resultCompleted = Number(result.completed || 0);
            const resultSuccess = Number(result.success_count || 0);
            const resultFailure = Number(result.failure_count ?? Math.max(0, resultCompleted - resultSuccess));
            this.fnImpulseProgress = {
                ...this.fnImpulseProgress,
                total: resultTotal,
                completed: resultCompleted,
                success_count: resultSuccess,
                failure_count: resultFailure,
                direction_attempt_count: Number(result.direction_attempt_count || 0),
                analyzed_direction_count: Number(result.analyzed_direction_count || 0),
                timeout_count: Number(result.timeout_count || 0),
                capture_failed_count: Number(result.capture_failed_count || 0),
                analysis_failed_count: Number(result.analysis_failed_count || 0),
                agent_unavailable_count: Number(result.agent_unavailable_count || 0),
                other_failure_count: Number(result.other_failure_count || 0),
                running_count: 0,
                queued_count: Math.max(0, resultTotal - resultCompleted),
                state: result.aborted ? 'aborted' : 'completed',
                action: result.aborted
                    ? 'Aborted'
                    : `Complete: ${resultSuccess} modems with analysis`,
                elapsed_s: Number(result.elapsed_s || this.fnImpulseProgress?.elapsed_s || 0),
                pct: resultTotal ? (resultCompleted * 100 / resultTotal) : 0,
                done: true,
            };
            return result;
        },

        _mergeFiberNodeImpulseCaptureResults(baseResult, captureResults, captureCounts) {
            const modems = (baseResult?.modems || []).map(modem => ({
                ...modem,
                results: [...(modem.results || [])],
                direction_statuses: (modem.direction_statuses || []).map(state => ({ ...state })),
                warnings: [...(modem.warnings || [])],
            }));
            const modemByMac = new Map(
                modems.map(modem => [this.normalizeMacForMatch(modem.mac_address), modem])
            );

            for (const captureResult of captureResults) {
                const direction = captureResult?.direction;
                if (!['downstream', 'upstream'].includes(direction)) continue;
                for (const captured of (captureResult?.modems || [])) {
                    const modem = modemByMac.get(this.normalizeMacForMatch(captured?.mac_address));
                    if (!modem) continue;
                    const captureState = (captured.direction_statuses || []).find(state => state.direction === direction);
                    const stateIndex = modem.direction_statuses.findIndex(
                        state => state.direction === direction && state.status === 'missing'
                    );
                    if (stateIndex >= 0 && captureState) modem.direction_statuses.splice(stateIndex, 1, { ...captureState });
                    const capturedItems = (captured.results || []).filter(item => item.direction === direction);
                    if (capturedItems.length) {
                        modem.results = modem.results.filter(item => item.direction !== direction).concat(capturedItems);
                    }
                    if (captured.warnings?.length) modem.warnings.push(...captured.warnings);
                    modem.success = modem.results.length > 0;
                }
            }

            const successCount = modems.filter(modem => modem.results.length > 0).length;
            const completed = Number(baseResult?.completed || baseResult?.total || modems.length);
            return {
                ...baseResult,
                success: successCount > 0,
                retrieval_mode: 'fresh_agent_catalog_with_missing_capture',
                missing_capture: { ...captureCounts },
                success_count: successCount,
                failure_count: Math.max(0, completed - successCount),
                modems,
            };
        },

        async runFiberNodeImpulse() {
            const scopedTargets = this._fiberNodeImpulseScopeTargets(true);
            if (!scopedTargets.length) {
                this.$toast?.warning('No modems are available in the current fiber-node scope');
                return;
            }
            const targets = scopedTargets.filter(target => (
                target.ip_address
                && target.ip_address.length <= 64
                && /^[0-9a-f:.]+$/i.test(target.ip_address)
            ));
            const skipped = scopedTargets.length - targets.length;
            if (!targets.length) {
                this.$toast?.warning('No selected modem has a valid current IP address for a new PNM capture');
                return;
            }
            if (skipped) {
                this.$toast?.warning(`Skipped ${skipped} modem${skipped === 1 ? '' : 's'} without a valid current IP address`);
            }
            const velocityFactor = this.requireVelocityFactor(this.fnImpulseVelocityFactor);
            if (velocityFactor === null) return;

            if (!(await this.prepareUiTask('Fiber Node Impulse Response'))) return;
            const { token, signal } = this._beginUiTask('Fiber Node Impulse Response');
            this.fnImpulseRunning = true;
            this.fnImpulseResult = null;
            this._destroyFiberNodeImpulseCharts();

            try {
                const result = await this._runFiberNodeImpulseJob({
                    targets,
                    source: 'fresh',
                    direction: this.fnImpulseDirection,
                    velocityFactor,
                    token,
                    signal,
                });
                if (!result) return;
                this.fnImpulseResult = result;
                await this.$nextTick();
                this.renderFiberNodeImpulseCharts();
                const summary = `${result.success_count || 0}/${result.completed || result.total || 0} modems with analysis`;
                if (result.success) this.$toast?.success(`New PNM capture and impulse analysis complete: ${summary}`);
                else this.$toast?.warning(`New PNM capture completed with no usable analysis data: ${summary}`);
            } catch (error) {
                if (error?.name === 'AbortError') return;
                this.fnImpulseResult = { success: false, error: error.message, modems: [] };
                this.$toast?.error(error.message || 'Bulk impulse-response capture failed');
            } finally {
                if (this._isTaskActive(token)) {
                    this.fnImpulseRunning = false;
                    this.fnImpulseJobId = null;
                    this._activeTaskLabel = null;
                }
            }
        },

        async captureMissingFiberNodeImpulse() {
            const plan = [...this.fnImpulseMissingCapturePlan];
            if (!plan.length || this.fnImpulseRunning) return;

            const currentByMac = new Map();
            for (const modem of [...(this.modems || []), ...(this.fnScanFilteredModems || [])]) {
                const normalized = this.normalizeMacForMatch(modem?.mac_address);
                if (normalized) currentByMac.set(normalized, modem);
            }
            const grouped = { downstream: [], upstream: [] };
            let skipped = 0;
            for (const item of plan) {
                const modem = currentByMac.get(this.normalizeMacForMatch(item.mac_address));
                const ipAddress = String(modem?.ip_address || '').trim();
                if (!ipAddress || ipAddress.length > 64 || !/^[0-9a-f:.]+$/i.test(ipAddress)) {
                    skipped += 1;
                    continue;
                }
                grouped[item.direction].push({ mac_address: item.mac_address, ip_address: ipAddress });
            }
            const counts = {
                downstream: grouped.downstream.length,
                upstream: grouped.upstream.length,
            };
            const operationCount = counts.downstream + counts.upstream;
            if (!operationCount) {
                this.$toast?.warning('No missing-file targets currently have a valid modem IP address');
                return;
            }
            if (skipped) {
                this.$toast?.warning(`Skipped ${skipped} missing-file operation${skipped === 1 ? '' : 's'} without a current valid modem IP address`);
            }
            const velocityFactor = this.requireVelocityFactor(this.fnImpulseVelocityFactor);
            if (velocityFactor === null) return;
            if (!(await this.prepareUiTask('Capture Missing PNM Files'))) return;

            const { token, signal } = this._beginUiTask('Capture Missing PNM Files');
            this.fnImpulseRunning = true;
            const baseResult = this.fnImpulseResult;
            const captureResults = [];
            try {
                for (const direction of ['downstream', 'upstream']) {
                    if (!grouped[direction].length) continue;
                    const result = await this._runFiberNodeImpulseJob({
                        targets: grouped[direction],
                        source: 'fresh',
                        direction,
                        velocityFactor,
                        token,
                        signal,
                    });
                    if (!result) return;
                    captureResults.push(result);
                    this.fnImpulseResult = this._mergeFiberNodeImpulseCaptureResults(
                        baseResult,
                        captureResults,
                        counts
                    );
                    await this.$nextTick();
                    this.renderFiberNodeImpulseCharts();
                }
                const captured = captureResults.reduce((total, result) => total + Number(result.success_count || 0), 0);
                if (captured) this.$toast?.success(`Missing-file capture analyzed ${captured}/${operationCount} operations`);
                else this.$toast?.warning('Missing-file capture completed without analyzable data');
            } catch (error) {
                if (error?.name === 'AbortError') return;
                this.$toast?.error(error.message || 'Missing-file capture failed');
            } finally {
                if (this._isTaskActive(token)) {
                    this.fnImpulseRunning = false;
                    this.fnImpulseJobId = null;
                    this._activeTaskLabel = null;
                }
            }
        },

        async abortFiberNodeImpulse() {
            if (!this.fnImpulseJobId || !this.fnImpulseRunning) return;
            const jobId = this.fnImpulseJobId;
            try {
                const response = await fetch(
                    `${API_BASE}/pypnm/impulse-response/fibernode/jobs/${encodeURIComponent(jobId)}`,
                    { method: 'DELETE' }
                );
                if (!response.ok) throw new Error('Cancellation request failed');
                this._taskGeneration += 1;
                if (this._currentFetchController) {
                    try { this._currentFetchController.abort(); } catch (_) {}
                    this._currentFetchController = null;
                }
                this.fnImpulseRunning = false;
                this.fnImpulseJobId = null;
                this._activeTaskLabel = null;
                if (this.fnImpulseProgress) {
                    this.fnImpulseProgress = {
                        ...this.fnImpulseProgress,
                        state: 'aborted',
                        action: 'Cancellation requested',
                        running_count: 0,
                        queued_count: 0,
                        done: true,
                    };
                }
            } catch (_) {
                this.$toast?.error('Could not request bulk impulse cancellation');
            }
        },

        async scanFiberNodeGroup() {
            if (!this.fnScanCmtsIp || !this.fnScanCommunity) {
                this.$toast?.error('CMTS IP and community required');
                return;
            }

            if (this.fnScanUseModemSelector && this.fnScanSelectedModemMacs.length > 0) {
                const selectedNorm = new Set(this.fnScanSelectedModemMacs.map(m => this.normalizeMacForMatch(m)).filter(Boolean));
                const selectedRows = this.fnScanFilteredModems.filter(m => selectedNorm.has(this.normalizeMacForMatch(m.mac_address)));
                const invalidMacs = selectedRows
                    .filter(m => !this.fnScanModemSupportsUsRxmer(m))
                    .map(m => m.mac_address);

                if (invalidMacs.length > 0) {
                    const invalidSet = new Set(invalidMacs.map(m => this.normalizeMacForMatch(m)).filter(Boolean));
                    this.fnScanSelectedModemMacs = this.fnScanSelectedModemMacs.filter(mac => !invalidSet.has(this.normalizeMacForMatch(mac)));
                    const remaining = this.fnScanSelectedModemMacs.length;
                    if (remaining === 0) {
                        this.$toast?.warning(
                            `No OFDMA-capable modems remain for US RxMER. You can still run DS Suckout or Fullband scans in this FiberNode view.`
                        );
                        return;
                    }
                    this.$toast?.warning(
                        `Skipped ${invalidMacs.length} non-OFDMA modem${invalidMacs.length === 1 ? '' : 's'}; continuing US RxMER with ${remaining} eligible modem${remaining === 1 ? '' : 's'}.`
                    );
                }
            }

            if (this.fnScanUseModemSelector && this.fnScanSelectedModemMacs.length > 0) {
                const selectedRowsByMac = new Map((this.fnScanBaseModems || []).map(modem => [
                    this.normalizeMacForMatch(modem?.mac_address),
                    modem,
                ]));
                const selectedRows = this.fnScanSelectedModemMacs.map(mac => (
                    selectedRowsByMac.get(this.normalizeMacForMatch(mac)) || {
                        mac_address: mac,
                        cmts_ip: this.fnScanCmtsIp,
                    }
                ));
                this.queueSelectedModemEnrichment(selectedRows, {
                    scope: 'Fiber Node selection',
                    maxBatch: 20,
                    cmts: this.fnScanCmts?.name || this.fnScanCmtsIp,
                });
            }

            if (!(await this.prepareUiTask('Fiber Node Scan'))) return;
            const { token, signal } = this._beginUiTask('Fiber Node Scan');
            // Generate a unique scan ID for progress polling
            const scanId = crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2);
            this.fnScanId       = scanId;
            this.fnScanRunning  = true;
            this.fnScanStartedAt = Date.now();
            this.fnScanAbortRequested = false;
            this.fnScanResult   = null;
            this.fnScanImage    = null;
            this.fnScanPlantAssessment = null;
            this.fnScanTapPlotImage   = null;
            this.fnScanTapProfile     = null;
            this.fnScanProgress = {
                step: 0, total: 0, modem: '', modem_idx: 0, modem_total: 0,
                phase: 'discovery', phase_current: 0, phase_total: 0,
                action: 'Starting…', pct: 0, done: false,
            };
            this.fnConfigCollapsed = false; // keep panel open so progress stays in-page

            try {
                const response = await fetch(`${API_BASE}/pypnm/cmts/ofdma/rxmer/fibernode/scan`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        scan_id:             scanId,
                        cmts_ip:             this.fnScanCmtsIp,
                        community:           this.fnScanCommunity,
                        write_community:     this.fnScanWriteCommunity || this.fnScanCommunity,
                        ofdma_ifindices:     [parseInt(this.fnScanIfindex), ...this.fnScanExtraIfindices].filter(Boolean),
                        fiber_node:          this.fnScanFiberNode || null,
                        preeq_enabled:       this.fnScanPreEq,
                        compare_preeq:       this.fnScanComparePreEq,
                        include_group_delay: this.fnScanGroupDelay,
                        tftp_path:           '/var/lib/tftpboot',
                        max_modems:          Math.max(2, parseInt(this.fnScanMaxModems) || 20),
                        selected_macs:       this.fnScanUseModemSelector ? this.fnScanSelectedModemMacs : [],
                    }),
                    signal,
                });
                const startResp = await response.json();
                if (!this._isTaskActive(token)) return;
                let result = null;
                // Backend runs scan in background thread and returns immediately
                if (startResp.started) {
                    const maxWaitMs = 15 * 60 * 1000; // 15 minutes
                    const waitStart = Date.now();
                    // Poll progress until done=true, then fetch result
                    await new Promise(resolve => {
                        this._fnScanWaitTimer = setInterval(async () => {
                            try {
                                const pr = await fetch(`${API_BASE}/pypnm/cmts/ofdma/rxmer/fibernode/scan/progress?scan_id=${scanId}`);
                                const pd = await pr.json();
                                if (this._isTaskActive(token) && pd.found) this._applyFnScanProgress(pd);
                                if (pd.done || (Date.now() - waitStart) > maxWaitMs) {
                                    clearInterval(this._fnScanWaitTimer);
                                    this._fnScanWaitTimer = null;
                                    resolve();
                                }
                            } catch (_) {}
                        }, 2000);
                    });
                    // Fetch result — retry a few times in case Redis write is slightly delayed
                    for (let attempt = 0; attempt < 5; attempt++) {
                        const rr = await fetch(`${API_BASE}/pypnm/cmts/ofdma/rxmer/fibernode/scan/result?scan_id=${scanId}`);
                        result = await rr.json();
                        if (!this._isTaskActive(token) || result.found) break;
                        await new Promise(r => setTimeout(r, 1000));
                    }
                    if (!this._isTaskActive(token)) return;
                    if (!result || !result.found) {
                        result = { success: false, error: 'Scan finished but result was not found (timeout or Redis issue)' };
                    }
                } else {
                    result = startResp;  // legacy sync response fallback
                }
                if (result.success) {
                    this.fnScanResult = result.analysis || { success: true, summary: null };
                    this.fnScanImage  = result.image_data;
                    if (result.group_delay) {
                        this.fnScanResult.group_delay = result.group_delay;
                    }
                    if (result.plant_assessment) {
                        this.fnScanPlantAssessment = result.plant_assessment;
                    }
                    if (result.tap_plot_image) {
                        this.fnScanTapPlotImage = result.tap_plot_image;
                    }
                    this.fnScanTapProfile = result.tap_profile || null;
                    this.$nextTick(() => this.renderBulkFiberNodeCharts());
                    const scanRowsByMac = new Map((this.fnScanBaseModems || []).map(modem => [
                        this.normalizeMacForMatch(modem?.mac_address),
                        modem,
                    ]));
                    const capturedRows = (result.captures || []).map(capture => {
                        const rawMac = capture?.cm_mac_address || capture?.mac_address || '';
                        return scanRowsByMac.get(this.normalizeMacForMatch(rawMac)) || {
                            mac_address: rawMac,
                            cmts_ip: this.fnScanCmtsIp,
                        };
                    });
                    this.queueSelectedModemEnrichment(capturedRows, {
                        scope: 'Fiber Node scan modems',
                        maxBatch: 20,
                        cmts: this.fnScanCmts?.name || this.fnScanCmtsIp,
                    });
                    const s = result.analysis?.summary;
                    this.$toast?.success(`Scanned ${s?.num_modems} modems — ${s?.pct_network_impaired?.toFixed(1)}% network-impaired`);
                } else {
                    this.fnScanResult = { success: false, error: result.error || 'Scan failed' };
                    if (result.aborted) {
                        this.$toast?.info('Fiber node scan aborted');
                    } else {
                        this.$toast?.error(result.error || 'Scan failed');
                    }
                }
            } catch (error) {
                if (error?.name === 'AbortError') return;
                this.fnScanResult = { success: false, error: error?.message || 'Scan request failed' };
                this.$toast?.error('Scan request failed');
            } finally {
                if (this._fnScanPollTimer) { clearInterval(this._fnScanPollTimer); this._fnScanPollTimer = null; }
                if (this._fnScanWaitTimer) { clearInterval(this._fnScanWaitTimer); this._fnScanWaitTimer = null; }
                this.fnScanRunning  = false;
                this.fnScanProgress = null;
                this.fnScanStartedAt = null;
                this.fnScanAbortRequested = false;
                this.fnConfigCollapsed = false;  // re-expand config panel when done
                if (this._activeTaskLabel === 'Fiber Node Scan') this._activeTaskLabel = null;
            }
        },

        async abortFnScan() {
            if (!this.fnScanId || !this.fnScanRunning || this.fnScanAbortRequested) return;
            this.fnScanAbortRequested = true;
            try {
                await fetch(`${API_BASE}/pypnm/cmts/ofdma/rxmer/fibernode/scan/abort`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ scan_id: this.fnScanId }),
                });
                if (this.fnScanProgress) {
                    this.fnScanProgress = { ...this.fnScanProgress, action: 'Abort requested...' };
                }
                this.$toast?.info('Abort requested. Waiting for backend to stop...');
            } catch (e) {
                this.fnScanAbortRequested = false;
                this.$toast?.error('Could not send abort request');
            }
        },

        // ── DS Channel Estimation Suckout Scan ────────────────────────────────
        async runDsSuckoutScan() {
            if (!this.fnScanCmtsIp) {
                this.$toast?.error('Select a CMTS in the scan configuration panel first');
                return;
            }
            if (!(await this.prepareUiTask('DS Suckout Scan'))) return;
            const { token, signal } = this._beginUiTask('DS Suckout Scan');
            this.dsScanRunning  = true;
            this.dsScanResult   = null;
            this.dsScanCollapsed = false;   // expand so progress bar is visible
            this.dsScanProgress = { total: 0, started: 0, completed: 0, pct: 0, modem: '', action: 'Discovering modems…' };
            const dsScanId = crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2);

            // Poll progress every 2 s while scan runs
            this._dsPollTimer = setInterval(async () => {
                try {
                    const pr = await fetch(`${API_BASE}/pypnm/ds/chan_est/scan/progress?scan_id=${dsScanId}`);
                    const pd = await pr.json();
                    if (this._isTaskActive(token) && pd.found) this.dsScanProgress = pd;
                } catch (_) {}
            }, 2000);

            try {
                // Use modems from loaded modem table filtered by selected fiber node
                const fnName = this.fnScanFiberNode;
                const fnModems = fnName
                    ? this.modems.filter(m => m.fiber_node === fnName && m.ip_address && m.status === 'operational')
                    : this.modems.filter(m => m.ip_address && m.status === 'operational');
                const maxDs = Math.max(2, parseInt(this.fnScanMaxModems) || 20);
                const selectedModems = fnModems.slice(0, maxDs).map(m => ({
                    mac_address: m.mac_address,
                    ip_address:  m.ip_address,
                }));
                const payload = {
                    scan_id:               dsScanId,
                    cmts_hostname:         this.fnScanCmts?.name || this.fnScanCmts?.hostname,
                    cmts_ip:               this.fnScanCmtsIp,
                    community:             this.fnScanCommunity || this.snmpCommunity,
                    modem_write_community: this.snmpCommunityModem,
                    max_modems:            maxDs,
                };
                if (selectedModems.length) payload.modems = selectedModems;
                const resp = await fetch(`${API_BASE}/pypnm/ds/chan_est/scan`, {
                    method:  'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                    signal,
                });
                const result = await resp.json();
                if (!this._isTaskActive(token)) return;
                if (result.success) {
                    this.dsScanResult = result;
                    this.$nextTick(() => {
                        this.renderDsOverlayChart();
                        this.renderDsSuckoutHeatmap();
                    });
                } else {
                    this.$toast?.error(result.error || 'DS suckout scan failed');
                }
            } catch (err) {
                if (err?.name === 'AbortError') return;
                this.$toast?.error(`Scan error: ${err.message}`);
            } finally {
                if (this._dsPollTimer) { clearInterval(this._dsPollTimer); this._dsPollTimer = null; }
                this.dsScanRunning  = false;
                this.dsScanProgress = null;
                if (this._activeTaskLabel === 'DS Suckout Scan') this._activeTaskLabel = null;
            }
        },

        async runFullbandScan() {
            if (!(await this.prepareUiTask('DS Fullband Scan'))) return;
            const { token, signal } = this._beginUiTask('DS Fullband Scan');
            const fbScanId = 'fb_' + Date.now();
            this.fbScanRunning  = true;
            this.fbScanResult   = null;
            this.fbScanCollapsed = false;
            this.fbScanProgress = { total: 0, started: 0, completed: 0, pct: 0, modem: '', action: 'Starting fullband scan…' };

            this._fbPollTimer = setInterval(async () => {
                try {
                    const pr = await fetch(`${API_BASE}/pypnm/ds/chan_est/scan/progress?scan_id=${fbScanId}`);
                    const pd = await pr.json();
                    if (this._isTaskActive(token) && pd.found) this.fbScanProgress = pd;
                } catch (_) {}
            }, 2000);

            try {
                const fnName = this.fnScanFiberNode;
                const fnModems = fnName
                    ? this.modems.filter(m => m.fiber_node === fnName && m.ip_address && m.status === 'operational')
                    : this.modems.filter(m => m.ip_address && m.status === 'operational');
                const maxFb = Math.max(2, parseInt(this.fnScanMaxModems) || 10);
                const selectedModems = fnModems.slice(0, maxFb).map(m => ({
                    mac_address: m.mac_address,
                    ip_address:  m.ip_address,
                }));
                const payload = {
                    scan_id:               fbScanId,
                    cmts_hostname:         this.fnScanCmts?.name || this.fnScanCmts?.hostname,
                    cmts_ip:               this.fnScanCmtsIp,
                    community:             this.fnScanCommunity || this.snmpCommunity,
                    modem_write_community: this.snmpCommunityModem,
                    max_modems:            maxFb,
                    strict_in_channel:     this.fbScanStrictInChannel,
                };
                if (selectedModems.length) payload.modems = selectedModems;
                const resp = await fetch(`${API_BASE}/pypnm/ds/fullband/scan`, {
                    method:  'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                    signal,
                });
                const result = await resp.json();
                if (!this._isTaskActive(token)) return;
                if (result.success) {
                    this.fbScanResult = result;
                    this.$nextTick(() => this.renderFullbandOverlayChart());
                } else {
                    this.$toast?.error(result.error || 'Fullband scan failed');
                }
            } catch (err) {
                if (err?.name === 'AbortError') return;
                this.$toast?.error(`Fullband scan error: ${err.message}`);
            } finally {
                if (this._fbPollTimer) { clearInterval(this._fbPollTimer); this._fbPollTimer = null; }
                this.fbScanRunning  = false;
                this.fbScanProgress = null;
                if (this._activeTaskLabel === 'DS Fullband Scan') this._activeTaskLabel = null;
            }
        },

        renderDsSuckoutHeatmap() {
            const canvas = document.getElementById('dsSuckoutHeatmap');
            if (!canvas || !this.dsScanResult) return;
            const modems = this.dsScanResult.modems.filter(modem => modem.success && modem.channels?.length);
            if (!modems.length) { canvas.style.display = 'none'; return; }

            const allAmps = modems.map(modem => modem.channels[0].amplitudes_db || []);
            const numCols = Math.min(...allAmps.map(values => values.length));
            if (!Number.isFinite(numCols) || numCols < 1) return;
            const step = Math.max(1, Math.floor(numCols / 600));
            const cols = Math.ceil(numCols / step);
            const cssWidth = Math.max(320, Math.floor(canvas.parentElement?.clientWidth || 800));
            const cellW = cssWidth / cols;
            const cellH = 22;
            const cssHeight = modems.length * cellH;
            const dpr = Math.max(1, window.devicePixelRatio || 1);
            this._dsHeatmapRenderedWidth = cssWidth;
            if (window.ResizeObserver && canvas.parentElement) {
                this._dsHeatmapResizeObserver?.disconnect();
                this._dsHeatmapResizeObserver = new ResizeObserver(entries => {
                    const width = Math.max(320, Math.floor(entries[0]?.contentRect?.width || 0));
                    if (Math.abs(width - (this._dsHeatmapRenderedWidth || 0)) > 2) {
                        requestAnimationFrame(() => this.renderDsSuckoutHeatmap());
                    }
                });
                this._dsHeatmapResizeObserver.observe(canvas.parentElement);
            }

            canvas.style.display = 'block';
            canvas.style.width = `${cssWidth}px`;
            canvas.style.height = `${cssHeight}px`;
            canvas.width = Math.round(cssWidth * dpr);
            canvas.height = Math.round(cssHeight * dpr);
            const ctx = canvas.getContext('2d');
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            ctx.clearRect(0, 0, cssWidth, cssHeight);

            let globalMin = Infinity;
            let globalMax = -Infinity;
            for (const values of allAmps) {
                for (let index = 0; index < numCols; index += step) {
                    const value = Number(values[index]);
                    if (!Number.isFinite(value)) continue;
                    globalMin = Math.min(globalMin, value);
                    globalMax = Math.max(globalMax, value);
                }
            }
            if (!Number.isFinite(globalMin) || !Number.isFinite(globalMax)) return;
            const range = globalMax - globalMin || 1;
            const toColor = value => {
                const t = Math.max(0, Math.min(1, (value - globalMin) / range));
                const r = Math.round(255 * Math.min(1, t * 2));
                const g = Math.round(255 * Math.max(0, t * 2 - 0.5));
                const b = Math.round(255 * Math.max(0, (1 - t) * 1.4));
                return `rgb(${r},${g},${b})`;
            };
            const sampledIndices = [];
            for (let index = 0; index < numCols; index += step) sampledIndices.push(index);

            for (let row = 0; row < modems.length; row++) {
                const amplitudes = allAmps[row];
                const sampledValues = sampledIndices.map(index => Number(amplitudes[index]));
                const regression = this._linRegY(sampledIndices, sampledValues);
                sampledIndices.forEach((sourceIndex, column) => {
                    const value = Number.isFinite(sampledValues[column]) ? sampledValues[column] : globalMin;
                    const dip = (value - regression[column]) < -this.dsScanThreshold;
                    ctx.fillStyle = dip ? '#dc3545' : toColor(value);
                    ctx.fillRect(column * cellW, row * cellH, Math.ceil(cellW) + 0.5, cellH);
                });
                ctx.strokeStyle = 'rgba(255,255,255,0.22)';
                ctx.beginPath();
                ctx.moveTo(0, (row + 1) * cellH);
                ctx.lineTo(cssWidth, (row + 1) * cellH);
                ctx.stroke();
            }

            const channel = modems[0].channels[0];
            const centerMhz = Number(channel.center_freq_mhz);
            const subcarrierCount = Number(channel.subcarrier_count || numCols);
            const frequencyForIndex = index => Number.isFinite(centerMhz)
                ? centerMhz + ((index / subcarrierCount) - 0.5) * 192
                : null;
            ctx.fillStyle = 'rgba(255,255,255,0.88)';
            ctx.font = '9px ui-monospace,monospace';
            const tickEvery = Math.max(1, Math.floor(cols / 10));
            for (let column = 0; column < cols; column += tickEvery) {
                const x = column * cellW;
                ctx.fillRect(x, 0, 1, cssHeight);
                const frequency = frequencyForIndex(column * step);
                ctx.fillText(frequency == null ? `sc${column * step}` : `${frequency.toFixed(0)}M`, x + 2, 10);
            }

            this._dsHeatmapMeta = { modems, allAmps, step, cols, cellW, cellH, cssWidth, cssHeight, frequencyForIndex };
            canvas.setAttribute('aria-label', this.dsHeatmapAccessibilitySummary());
            canvas.setAttribute('tabindex', '0');
            const tooltip = document.getElementById('dsHeatmapTooltip');
            if (this._dsHeatmapMoveHandler) canvas.removeEventListener('pointermove', this._dsHeatmapMoveHandler);
            if (this._dsHeatmapLeaveHandler) canvas.removeEventListener('pointerleave', this._dsHeatmapLeaveHandler);
            this._dsHeatmapMoveHandler = event => {
                const meta = this._dsHeatmapMeta;
                if (!meta || !tooltip) return;
                const rect = canvas.getBoundingClientRect();
                const column = Math.max(0, Math.min(meta.cols - 1, Math.floor((event.clientX - rect.left) / rect.width * meta.cols)));
                const row = Math.max(0, Math.min(meta.modems.length - 1, Math.floor((event.clientY - rect.top) / rect.height * meta.modems.length)));
                const sourceIndex = column * meta.step;
                const value = Number(meta.allAmps[row][sourceIndex]);
                const frequency = meta.frequencyForIndex(sourceIndex);
                tooltip.textContent = `${meta.modems[row].mac_address} · ${frequency == null ? `SC ${sourceIndex}` : `${frequency.toFixed(3)} MHz`} · ${Number.isFinite(value) ? value.toFixed(2) : 'N/A'} dB`;
                tooltip.style.display = 'block';
                tooltip.style.left = `${event.clientX - rect.left + 12}px`;
                tooltip.style.top = `${event.clientY - rect.top + 12}px`;
            };
            this._dsHeatmapLeaveHandler = () => { if (tooltip) tooltip.style.display = 'none'; };
            canvas.addEventListener('pointermove', this._dsHeatmapMoveHandler);
            canvas.addEventListener('pointerleave', this._dsHeatmapLeaveHandler);
        },

        dsHeatmapAccessibilitySummary() {
            const modemCount = this.dsScanResult?.modems?.filter(modem => modem.success && modem.channels?.length).length || 0;
            const suckouts = this.dsSuckoutSummary();
            const networkCount = suckouts.filter(item => item.verdict === 'Network').length;
            return `Amplitude heatmap for ${modemCount} modems. ${suckouts.length} suckout clusters detected, including ${networkCount} network clusters. Red cells are at least ${this.dsScanThreshold} dB below each modem trend.`;
        },

        dsSuckoutSummary() {
            if (!this.dsScanResult) return [];
            const modems = this.dsScanResult.modems.filter(m => m.success && m.channels?.length);
            if (modems.length < 2) return [];
            // Per-modem suckout detection in subcarrier-index domain
            const perModem = modems.map(m => {
                const ch  = m.channels[0];
                const idx = Array.from({length: ch.amplitudes_db.length}, (_, i) => i);
                const reg = this._linRegY(idx, ch.amplitudes_db);
                const s   = this._detectSuckouts(idx, ch.amplitudes_db, reg, this.dsScanThreshold);
                // Annotate with approximate MHz if center_freq_mhz available
                if (ch.center_freq_mhz != null) {
                    const n = ch.subcarrier_count;
                    s.forEach(sk => {
                        sk.freq_mhz = parseFloat((ch.center_freq_mhz + (sk.freq_mhz / n - 0.5) * 192).toFixed(1));
                        sk.start_mhz = parseFloat((ch.center_freq_mhz + (sk.start_mhz / n - 0.5) * 192).toFixed(1));
                        sk.end_mhz   = parseFloat((ch.center_freq_mhz + (sk.end_mhz   / n - 0.5) * 192).toFixed(1));
                        sk.width_mhz = parseFloat((sk.end_mhz - sk.start_mhz).toFixed(1));
                    });
                }
                return { mac: m.mac_address, suckouts: s };
            });
            // Cluster by ±5 subcarrier indices (or ±5 MHz if freq available)
            const clusters = {};
            for (const m of perModem) {
                for (const s of m.suckouts) {
                    const k = Math.round(s.freq_mhz / 5) * 5;
                    if (!clusters[k]) clusters[k] = { freq_mhz: s.freq_mhz, macs: [], depths: [] };
                    clusters[k].macs.push(m.mac);
                    clusters[k].depths.push(s.depth_db);
                }
            }
            return Object.values(clusters)
                .sort((a, b) => a.freq_mhz - b.freq_mhz)
                .map(c => ({
                    freq_mhz:      c.freq_mhz,
                    modem_count:   c.macs.length,
                    max_depth:     Math.max(...c.depths),
                    verdict:       c.macs.length >= 3 ? 'Network' : (c.macs.length >= 2 ? 'Suspect' : 'In-home'),
                    verdict_class: c.macs.length >= 3 ? 'danger'  : (c.macs.length >= 2 ? 'warning' : 'secondary'),
                    macs:          c.macs,
                }));
        },
        
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
            const cfgParams = `&center_freq_hz=${this.utscConfig.centerFreqMhz * 1000000}&span_hz=${this.utscConfig.spanMhz * 1000000}&num_bins=${this.utscConfig.numBins}&output_format=${this.utscConfig.outputFormat}&window=${this.utscConfig.window}&runtime=${this.utscConfig.runtime}&cfg_index=${this.utscConfig.cfgIndex || 0}`;
            const communityParam = this.snmpCommunityRW ? `&community=${encodeURIComponent(this.snmpCommunityRW)}` : '';
            iframe.src = `${BASE_PATH}/spectrum-analyzer?mac=${encodeURIComponent(mac)}&rfport=${this.utscConfig.rfPortIfindex || ''}&cmts=${encodeURIComponent(this.selectedModem.cmts_ip || '')}${liveParam}${cfgParams}${communityParam}`;
            
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
            // Always send stop UTSC when spectrum analyzer is closed
            this.stopUtsc();
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
        
        closeUtscSpectrum() {
            this.utscSpectrumData = null;
            this.closeSpectrumAnalyzerModal();
        },
        
        closeUsRxmerSpectrum() {
            this.usRxmerSpectrumData = null;
            this.usRxmerCaptures = [];
            this.usRxmerDisplayIndex = 0;
            this._destroyChartSurface('surface-us-rxmer');
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
            
            // Configure UTSC - use user-selected triggerMode and params.
            // Only enforce device-safe timing minimums; cfgIndex auto-probed by backend.
            this.utscConfig.cfgIndex = 0;
            this.utscConfig.repeatPeriodMs = Math.max(this.utscConfig.repeatPeriodMs || 400, 400);
            this.utscConfig.freerunDurationMs = Math.max(this.utscConfig.freerunDurationMs || 120000, 120000);
            
            try {
                // Configure and start UTSC (vendor-aware defaults applied in PyPNM)
                const liveConfigResult = await this.configureUtsc();
                if (!liveConfigResult || !liveConfigResult.success) {
                    this.liveSpectrumEnabled = false;
                    return;
                }
                
                const response = await fetch(`${API_BASE}/pypnm/upstream/utsc/start/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip,
                        rf_port_ifindex: this.utscConfig.rfPortIfindex,
                        cfg_index: this.utscConfig.cfgIndex || 0,
                        trigger_mode: this.utscConfig.triggerMode || 2,
                        community: this.snmpCommunity,
                        write_community: this.snmpCommunityRW
                    })
                });
                
                const result = await response.json();
                if (result.success) {
                    const resolvedCfgIndex = Number.parseInt(result.cfg_index, 10);
                    if (!Number.isInteger(resolvedCfgIndex) || resolvedCfgIndex <= 0) {
                        this.$toast?.error('UTSC start returned no usable config row');
                        this.liveSpectrumEnabled = false;
                        return;
                    }
                    this.utscConfig.cfgIndex = resolvedCfgIndex;
                    this.$toast?.success('Live spectrum started');
                    this.runningUtsc = true;
                    // Open Pro Spectrum Analyzer (WS handles streaming, no HTTP polling needed)
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
            
            // Set up polling interval
            this.liveSpectrumIntervalId = setInterval(() => {
                if (this.liveSpectrumEnabled && this.runningUtsc) {
                    this.fetchLiveSpectrumData();
                }
            }, this.liveSpectrumIntervalMs + 100);
        },
        
        async fetchLiveSpectrumData() {
            if (!this.liveSpectrumEnabled || !this.selectedModem) return;
            
            const startTime = Date.now();
            
            try {
                const response = await fetch(`${API_BASE}/pypnm/upstream/utsc/data/${this.selectedModem.mac_address}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cmts_ip: this.selectedModem.cmts_ip,
                        rf_port_ifindex: this.utscConfig.rfPortIfindex,
                        filename: this.utscLastFilename,
                        vendor: this.selectedModem.vendor || '',
                        community: this.snmpCommunity,
                        write_community: this.snmpCommunityRW
                    })
                });
                
                const result = await response.json();
                
                if (result.success && result.data) {
                    // Casa/vCCAP often reuses a constant filename for successive
                    // captures. Deduplicate on file signature (name+mtime+size),
                    // not filename alone.
                    const currentFile = result.data.filename || null;
                    const currentSig = [
                        currentFile || '',
                        String(result.data.file_mtime ?? ''),
                        String(result.data.file_size ?? ''),
                    ].join('|');
                    this.utscLastFilename = currentFile || this.utscLastFilename;
                    if (currentSig && currentSig === this.liveSpectrumLastFile) {
                        return;  // No new capture yet
                    }
                    this.liveSpectrumLastFile = currentSig || currentFile;
                    
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

        async loadImpulseFiles() {
            if (!this.selectedModem || this.impulseSource !== 'existing') return;
            this.impulseFilesLoading = true;
            try {
                const response = await fetch(
                    `${API_BASE}/pypnm/impulse-response/${encodeURIComponent(this.selectedModem.mac_address)}/files?direction=${encodeURIComponent(this.impulseDirection)}`
                );
                const data = await response.json();
                if (!response.ok || !data.success) throw new Error(data.error || 'Could not list PNM files');
                this.impulseFiles = data.files || [];
                if (this.impulseFileId && !this.impulseFiles.some(file => file.file_id === this.impulseFileId)) {
                    this.impulseFileId = '';
                }
            } catch (error) {
                this.impulseFiles = [];
                this.impulseFileId = '';
                this.showError('PNM File Catalog', error.message);
            } finally {
                this.impulseFilesLoading = false;
            }
        },

        async runImpulseResponse() {
            if (!this.selectedModem?.ip_address) return;
            const velocityFactor = this.requireVelocityFactor(this.impulseVelocityFactor);
            if (velocityFactor === null) return;
            if (!(await this.prepareUiTask('OFDM/OFDMA Impulse Response'))) return;
            const { token, signal } = this._beginUiTask('OFDM/OFDMA Impulse Response', 'impulse_response');
            this.impulseSource = 'fresh';
            this.showRawData = false;
            try {
                const payload = {
                    source: 'fresh',
                    direction: this.impulseDirection,
                    velocity_factor: velocityFactor,
                    modem_ip: this.selectedModem.ip_address,
                    community: this.snmpCommunityModem,
                };
                const response = await fetch(
                    `${API_BASE}/pypnm/impulse-response/${encodeURIComponent(this.selectedModem.mac_address)}/analyze`,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload),
                        signal,
                    }
                );
                const data = await response.json();
                if (!this._isTaskActive(token)) return;
                if (!response.ok || !data.success) throw new Error(data.error || 'Impulse-response analysis failed');
                this.selectedMeasurementData = data;
                this.$nextTick(() => this.drawMeasurementCharts('impulse_response', data));
                this.showSuccess(
                    'Impulse Response Complete',
                    `${data.results?.length || 0} channel response(s) analyzed from fresh capture`
                );
            } catch (error) {
                if (error?.name === 'AbortError') return;
                this.showError('Impulse Response Failed', error.message);
            } finally {
                if (this._isTaskActive(token)) {
                    this.runningTest = false;
                    this.activeMeasurement = null;
                    this._activeTaskLabel = null;
                }
            }
        },

        async runPnmMeasurement(measurementType) {
            if (!this.selectedModem) return;
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
            const taskLabel = typeNames[measurementType] || measurementType;
            const { token, signal } = this._beginUiTask(taskLabel, measurementType);

            // A new request owns the result area. Clear stale data immediately so a
            // failed/aborted request cannot leave another measurement or modem visible.
            this.showRawData = false;
            const previousChartContainer = document.getElementById('measurement-charts-container');
            previousChartContainer?.querySelectorAll('canvas').forEach(canvas => {
                const chart = typeof Chart.getChart === 'function' ? Chart.getChart(canvas) : null;
                if (chart) chart.destroy();
            });
            this.selectedMeasurementData = null;
            this.rxmerData = null;
            this.spectrumData = null;
            this.fecData = null;
            this.preEqData = null;
            this.expandedPlotJson = [];
            
            try {
                const payload = {
                    modem_ip: this.selectedModem.ip_address,
                    community: this.snmpCommunityModem,
                    output_type: this.pnmOutputType
                };

                // For DS spectrum: use the 1850 MHz extended-spectrum upper
                // boundary while still allowing discovered channel data to
                // confirm the modem's actual upper band.
                if (measurementType === 'spectrum') {
                    let maxFreqHz = 1_850_000_000;
                    try {
                        const ofdmChs = this.channelStats?.downstream?.ofdm?.channels || [];
                        for (const ch of ofdmChs) {
                            // plc_freq_mhz is the OFDM PLC centre; end = plc + ~96 MHz for 192 MHz ch
                            const plcHz = (ch.plc_freq_mhz || 0) * 1e6;
                            const bwHz  = (ch.bandwidth_mhz  || 192) * 1e6;
                            const endHz = plcHz + bwHz / 2;
                            if (endHz > maxFreqHz) maxFreqHz = endHz;
                        }
                        // Round down to nearest MHz and keep the configured floor.
                        maxFreqHz = Math.floor(maxFreqHz / 1e6) * 1e6;
                        if (maxFreqHz < 1_850_000_000) maxFreqHz = 1_850_000_000;
                    } catch (e) { /* ignore; fallback stays */ }
                    payload.last_segment_center_freq_hz = maxFreqHz;
                }

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
                    body: JSON.stringify(payload),
                    signal,
                });
                
                const data = await response.json();
                if (!this._isTaskActive(token)) return;
                
                console.log('=== PNM Measurement Response ===');
                console.log('Status:', data.status);
                console.log('Has data field:', !!data.data);
                console.log('data.data:', data.data);
                console.log('Measurement type:', measurementType);
                console.log('Output type:', this.pnmOutputType);
                console.log('Plots:', data.plots);
                console.log('Plots count:', data.plots ? data.plots.length : 0);
                console.log('================================');
                
                const statusText = String(data.status ?? '').toLowerCase();
                const measurementSucceeded = data.status === 0
                    || data.status === '0'
                    || statusText === 'success'
                    || data.success === true;

                if (measurementSucceeded) {
                    // Preserve the untouched response for Raw Data and archive downloads.
                    this.selectedMeasurementData = data;

                    // Keep legacy state populated for old response shapes, but render all
                    // interactive responses through the canonical compatibility layer below.
                    if (measurementType === 'rxmer') {
                        this.rxmerData = data;
                    } else if (measurementType === 'spectrum') {
                        this.spectrumData = data;
                    } else if (measurementType === 'fec_summary') {
                        this.fecData = data;
                    } else if (measurementType === 'us_pre_eq') {
                        this.preEqData = data;
                    }

                    // Interactive mode always attempts Chart.js rendering. Archive mode
                    // retains Matplotlib when plots are present and only falls back to
                    // structured charts when the backend returned no plot artifacts.
                    const hasMatplotlibPlots = Array.isArray(data.plots) && data.plots.length > 0;
                    const useInteractiveCharts = this.pnmOutputType === 'json';

                    if (useInteractiveCharts || !hasMatplotlibPlots) {
                        this.$nextTick(() => this.drawMeasurementCharts(measurementType, data));
                    } else {
                        console.log(`Using ${data.plots.length} matplotlib plot(s) for ${measurementType}`);
                    }

                    this.showSuccess(
                        `${typeNames[measurementType] || measurementType} Complete`,
                        this.pnmOutputType === 'archive'
                            ? 'Plots and CSV data generated successfully'
                            : 'Measurement data retrieved successfully'
                    );
                } else {
                    this.showError('Measurement Failed', data.message || data.error || `Error code: ${data.status}`);
                }
            } catch (error) {
                if (error?.name === 'AbortError') return;
                console.error('PNM measurement failed:', error);
                this.showError('Measurement Failed', error.message);
            } finally {
                if (this._isTaskActive(token)) {
                    this.runningTest = false;
                    this.activeMeasurement = null;
                    this._activeTaskLabel = null;
                }
            }
        },
        
        togglePlotJson(filename) {
            const idx = this.expandedPlotJson.indexOf(filename);
            if (idx === -1) this.expandedPlotJson.push(filename);
            else this.expandedPlotJson.splice(idx, 1);
        },

        getPlotChannelData(filename) {
            const selected = this.selectedMeasurementData;
            const rxmerMeasurements = selected?.data?.rxmer_measurements;
            if (Array.isArray(rxmerMeasurements)) {
                const match = filename.match(/_(\d{1,3})_rxmer/i);
                if (match) {
                    const channelId = Number.parseInt(match[1], 10);
                    const channel = rxmerMeasurements.find(item => item.channel_id == channelId);
                    if (channel) return channel;
                }
            }
            return selected;
        },

        toggleRawData() {
            this.showRawData = !this.showRawData;
        },

        downloadChartData() {
            let payload = null;

            // The visible/current measurement is authoritative. Preserve its
            // canonical response exactly instead of rebuilding a lossy legacy DTO.
            if (this.selectedMeasurementData) {
                payload = {
                    type: 'measurement_data',
                    modem: this.selectedModem ? this.selectedModem.mac_address : null,
                    timestamp: new Date().toISOString(),
                    data: this.selectedMeasurementData
                };
            // UTSC spectrum chart data
            } else if (this.utscChartInstance && this.utscChartInstance.data) {
                const d = this.utscChartInstance.data;
                payload = {
                    type: 'utsc_spectrum',
                    modem: this.selectedModem ? this.selectedModem.mac_address : null,
                    timestamp: new Date().toISOString(),
                    frequency_mhz: d.labels,
                    amplitude_db: d.datasets[0] ? d.datasets[0].data : []
                };
            } else {
                alert('No chart data available to download.');
                return;
            }

            const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            const mac = payload.modem ? payload.modem.replace(/:/g, '') : 'unknown';
            a.download = `${payload.type}_${mac}_${Date.now()}.json`;
            a.click();
            URL.revokeObjectURL(url);
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
        
        normalizePnmResponse(type, response) {
            const payload = response && response.data !== undefined ? response.data : (response || {});
            const analyses = Array.isArray(payload?.analysis)
                ? payload.analysis
                : (Array.isArray(payload) ? payload : []);
            const normalized = { type, payload, analyses };

            if (type === 'rxmer') {
                const legacy = Array.isArray(payload?.rxmer_measurements) ? payload.rxmer_measurements : [];
                normalized.channels = legacy.length ? legacy.map(item => ({
                    channelId: item.channel_id,
                    firstActiveIndex: 0,
                    frequencies: [],
                    magnitudes: (item.subcarrier_samples || []).map(sample => Number(sample.mer_db)),
                    statuses: [],
                    indices: (item.subcarrier_samples || []).map(sample => Number(sample.subcarrier_index)),
                })) : analyses.map(item => {
                    const carrier = item.carrier_values || {};
                    const magnitudes = Array.isArray(carrier.magnitude) ? carrier.magnitude.map(Number) : [];
                    const firstActiveIndex = Number(item.first_active_subcarrier_index || 0);
                    return {
                        channelId: item.channel_id,
                        firstActiveIndex,
                        frequencies: Array.isArray(carrier.frequency) ? carrier.frequency.map(Number) : [],
                        magnitudes,
                        statuses: Array.isArray(carrier.carrier_status) ? carrier.carrier_status.map(Number) : [],
                        statusMap: carrier.carrier_status_map || {},
                        indices: magnitudes.map((_, index) => firstActiveIndex + index),
                    };
                });
            } else if (type === 'channel_estimation' || type === 'us_pre_eq') {
                normalized.channels = analyses;
            } else if (type === 'modulation_profile') {
                const profiles = [];
                if (Array.isArray(payload?.modulation_profiles)) {
                    payload.modulation_profiles.forEach(profile => profiles.push({
                        channelId: profile.channel_id ?? '?',
                        profileId: profile.profile_id,
                        carriers: (profile.subcarriers || []).map(item => ({
                            frequency: Number(item.frequency || item.index || 0),
                            modulation: item.modulation_order ?? item.modulation,
                            shannonMinMer: item.shannon_min_mer,
                        })),
                    }));
                } else {
                    analyses.forEach(channel => (channel.profiles || []).forEach(profile => {
                        const carrierValues = profile.carrier_values || {};
                        const carriers = carrierValues.layout === 'list'
                            ? (carrierValues.carriers || []).map(item => ({
                                frequency: Number(item.frequency),
                                modulation: item.modulation,
                                shannonMinMer: Number(item.shannon_min_mer),
                            }))
                            : (carrierValues.frequency || []).map((frequency, index) => ({
                                frequency: Number(frequency),
                                modulation: (carrierValues.modulation || [])[index],
                                shannonMinMer: Number((carrierValues.shannon_min_mer || [])[index]),
                            }));
                        profiles.push({ channelId: channel.channel_id, profileId: profile.profile_id, carriers });
                    }));
                }
                normalized.profiles = profiles;
            } else if (type === 'fec_summary') {
                const series = [];
                if (Array.isArray(payload?.fec_summaries)) {
                    payload.fec_summaries.forEach(item => series.push({
                        channelId: item.channel_id,
                        profileId: item.profile_id,
                        timestamps: ['Latest sample'],
                        total: [Number(item.total_codewords || 0)],
                        corrected: [Number(item.corrected_codewords || 0)],
                        uncorrected: [Number(item.uncorrectable_codewords || 0)],
                    }));
                } else {
                    analyses.forEach(channel => (channel.profiles || []).forEach(profile => {
                        const codewords = profile.codewords || {};
                        const count = Math.min(
                            (codewords.total_codewords || []).length,
                            (codewords.corrected || []).length,
                            (codewords.uncorrected || []).length
                        );
                        series.push({
                            channelId: channel.channel_id,
                            profileId: profile.profile,
                            timestamps: (codewords.timestamps || []).slice(0, count),
                            total: (codewords.total_codewords || []).slice(0, count).map(Number),
                            corrected: (codewords.corrected || []).slice(0, count).map(Number),
                            uncorrected: (codewords.uncorrected || []).slice(0, count).map(Number),
                        });
                    }));
                }
                normalized.series = series;
            } else if (type === 'histogram') {
                normalized.histograms = Array.isArray(payload?.histograms)
                    ? payload.histograms.map(item => ({
                        channelId: item.channel_id,
                        symmetry: item.symmetry,
                        dwellCounts: item.dwell_counts || [],
                        bins: item.bins || item.histogram_data || [],
                    }))
                    : analyses.map(item => ({
                        channelId: item.channel_id,
                        symmetry: item.symmetry,
                        dwellCounts: item.dwell_counts || [],
                        bins: (item.hit_counts || []).map((count, index) => ({ index, count: Number(count) })),
                    }));
            } else if (type === 'constellation') {
                normalized.constellations = Array.isArray(payload?.constellations)
                    ? payload.constellations.map(item => ({
                        channelId: item.channel_id,
                        soft: (item.points || []).map(point => [point.i ?? point.real, point.q ?? point.imag]),
                        hard: [],
                    }))
                    : analyses.map(item => ({
                        channelId: item.channel_id,
                        modulationOrder: item.modulation_order,
                        soft: item.soft || [],
                        hard: item.hard || [],
                    }));
            }

            return normalized;
        },

        drawMeasurementCharts(type, data) {
            const container = document.getElementById('measurement-charts-container');
            if (!container) {
                console.warn('Chart container not found');
                return;
            }

            container.querySelectorAll('canvas').forEach(canvas => {
                const chart = typeof Chart.getChart === 'function' ? Chart.getChart(canvas) : null;
                if (chart) chart.destroy();
            });
            container.innerHTML = '';

            console.log('Drawing charts for type:', type);
            if (type === 'impulse_response') {
                this.drawImpulseResponseCharts(data);
                return;
            }

            const normalized = this.normalizePnmResponse(type, data);
            if (type === 'spectrum') {
                if (normalized.analyses.length) this.drawSpectrumCharts(normalized.payload);
                else this.drawSpectrumFromChannels(normalized.payload);
            } else if (type === 'rxmer') {
                this.drawRxmerCharts(normalized);
            } else if (type === 'channel_estimation') {
                this.drawChannelEstimationCharts(normalized.channels || []);
            } else if (type === 'modulation_profile') {
                this.drawModulationProfileCharts(normalized);
            } else if (type === 'fec_summary') {
                this.drawFecSummaryCharts(normalized);
            } else if (type === 'histogram') {
                this.drawHistogramCharts(normalized);
            } else if (type === 'constellation') {
                this.drawConstellationCharts(normalized);
            } else if (type === 'us_pre_eq') {
                this.drawPreEqCharts(normalized);
            } else {
                container.innerHTML = '<div class="alert alert-info"><i class="bi bi-info-circle me-2"></i>No visualization available for this measurement type. Click "Raw Data" to see the results.</div>';
            }
        },
        
        drawImpulseResponseCharts(data) {
            const container = document.getElementById('measurement-charts-container');
            if (!container) return;
            const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({
                '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
            })[ch]);
            const warnings = data.warnings || [];
            if (warnings.length) {
                const warning = document.createElement('div');
                warning.className = 'alert alert-warning py-2';
                warning.textContent = warnings.join(' · ');
                container.appendChild(warning);
            }

            const results = data.results || [];
            if (!results.length) {
                container.innerHTML += '<div class="alert alert-warning">No impulse-response data returned.</div>';
                return;
            }

            // Frequency response is comparable across the returned OFDM/OFDMA
            // channels. Use one shared dB scale so a quiet channel is not
            // visually magnified relative to a channel with a large excursion.
            const frequencyValueSets = [];
            for (const item of results) {
                const magnitudes = item?.analysis?.carrier_values?.magnitudes;
                if (Array.isArray(magnitudes) && magnitudes.length) frequencyValueSets.push(magnitudes);
            }
            const frequencyDbAxis = this._dbAxisPolicy(frequencyValueSets);
            const impulseDbAxis = this._dbAxisPolicy([], {
                minimum: -70,
                maximum: 0,
                stepSize: 10,
            });
            const frequencyYTitle = `Magnitude (dB · ${frequencyDbAxis.dbPerDivision} dB/div)`;
            const impulseYTitle = `Relative magnitude (dB · ${impulseDbAxis.dbPerDivision} dB/div)`;

            results.forEach((item, resultIndex) => {
                const analysis = item.analysis || {};
                const report = analysis.echo?.report || {};
                const timeResponse = report.time_response || {};
                const times = timeResponse.time_axis_s || [];
                const amplitudes = timeResponse.time_response || [];
                const maxDelay = Number(report.max_delay_s || 3.5e-6);
                const timePoints = [];
                for (let i = 0; i < Math.min(times.length, amplitudes.length); i++) {
                    if (Number(times[i]) > maxDelay) break;
                    timePoints.push({
                        x: Number(times[i]) * 1e6,
                        y: 20 * Math.log10(Math.max(Number(amplitudes[i]), 1e-12)),
                    });
                }
                const echoes = report.echoes || [];
                const echoPoints = echoes.map(echo => ({
                    x: Number(echo.time_s) * 1e6,
                    y: 20 * Math.log10(Math.max(Number(echo.amplitude), 1e-12)),
                }));
                const carrier = analysis.carrier_values || {};
                const frequencies = carrier.frequency || [];
                const magnitudes = carrier.magnitudes || [];
                const freqStep = Math.max(1, Math.ceil(frequencies.length / 2500));
                const freqPoints = [];
                for (let i = 0; i < Math.min(frequencies.length, magnitudes.length); i += freqStep) {
                    freqPoints.push({ x: Number(frequencies[i]) / 1e6, y: Number(magnitudes[i]) });
                }
                const frequencyAxis = this._frequencyAxisPolicy(item.direction, [freqPoints]);

                const channelId = analysis.channel_id ?? report.channel_id ?? '?';
                const directionLabel = item.direction === 'upstream'
                    ? 'Upstream pre-equalizer response'
                    : 'Downstream channel response';
                const block = document.createElement('div');
                block.className = 'mb-4 border rounded p-3';
                block.innerHTML = `
                    <div class="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-2">
                        <div>
                            <h6 class="mb-1"><i class="bi bi-soundwave me-1"></i>${escapeHtml(directionLabel)} · Channel ${escapeHtml(channelId)}</h6>
                            <small class="text-muted">${escapeHtml(item.pnm_file_type)} · ${escapeHtml(item.filename || 'fresh capture')} · ${report.dataset?.subcarriers || 0} active carriers · FFT ${timeResponse.n_fft || report.dataset?.subcarriers || 0}</small>
                        </div>
                        <span class="badge bg-secondary">${escapeHtml(report.response_kind || 'detector_windowed')} / ${escapeHtml(report.window || 'hann')}</span>
                    </div>
                    <div class="row g-3">
                        <div class="col-lg-6"><canvas id="impulse-freq-${resultIndex}" height="230"></canvas></div>
                        <div class="col-lg-6"><canvas id="impulse-time-${resultIndex}" height="230"></canvas></div>
                    </div>
                    <div class="table-responsive mt-3">
                        <table class="table table-sm table-bordered mb-0">
                            <thead><tr><th>Echo</th><th>Delay (µs)</th><th>Distance (m)</th><th>Relative level (dB)</th><th>Bin</th></tr></thead>
                            <tbody>${echoes.length ? echoes.map((echo, index) => {
                                const reportedDistanceM = Number(echo.distance_m);
                                const distanceM = Number.isFinite(reportedDistanceM)
                                    ? reportedDistanceM
                                    : this.feetToMeters(echo.distance_ft);
                                const distanceLabel = Number.isFinite(distanceM) ? distanceM.toFixed(1) : '—';
                                return `<tr><td>${index + 1}</td><td>${(Number(echo.time_s) * 1e6).toFixed(3)}</td><td>${distanceLabel}</td><td>${(20 * Math.log10(Math.max(Number(echo.amplitude), 1e-12))).toFixed(1)}</td><td>${echo.bin_index}</td></tr>`;
                            }).join('') : '<tr><td colspan="5" class="text-muted">No prominent post-main-tap peaks detected</td></tr>'}</tbody>
                        </table>
                    </div>
                    <small class="text-muted d-block mt-2">Guard: ${report.guard_bins ?? '-'} bins · prominence: ${report.min_prominence_db ?? '-'} dB · sample rate: ${report.dataset?.sample_rate_hz ? (report.dataset.sample_rate_hz / 1e6).toFixed(1) + ' MHz' : '-'}</small>
                `;
                container.appendChild(block);

                const commonOptions = {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    parsing: false,
                    interaction: { mode: 'nearest', intersect: false },
                };
                const freqCanvas = block.querySelector(`#impulse-freq-${resultIndex}`);
                if (freqCanvas && freqPoints.length) {
                    new Chart(freqCanvas.getContext('2d'), {
                        type: 'line',
                        data: { datasets: [{ label: 'Magnitude (dB)', data: freqPoints, borderColor: '#0d6efd', borderWidth: 1, pointRadius: 0 }] },
                        options: {
                            ...commonOptions,
                            scales: {
                                x: {
                                    type: 'linear',
                                    ...frequencyAxis.xScale,
                                    title: { display: true, text: frequencyAxis.title },
                                },
                                y: {
                                    ...frequencyDbAxis.yScale,
                                    title: { display: true, text: frequencyYTitle },
                                },
                            },
                            plugins: { title: { display: true, text: 'Frequency Response' }, legend: { display: false } },
                        },
                    });
                }
                const timeCanvas = block.querySelector(`#impulse-time-${resultIndex}`);
                if (timeCanvas && timePoints.length) {
                    new Chart(timeCanvas.getContext('2d'), {
                        type: 'line',
                        data: { datasets: [
                            { label: 'Detector response', data: timePoints, borderColor: '#198754', borderWidth: 1, pointRadius: 0 },
                            { label: 'Detected echoes', data: echoPoints, showLine: false, pointRadius: 5, pointStyle: 'triangle', backgroundColor: '#dc3545' },
                        ] },
                        options: {
                            ...commonOptions,
                            scales: {
                                x: { type: 'linear', title: { display: true, text: 'Delay after main tap (µs)' } },
                                y: {
                                    ...impulseDbAxis.yScale,
                                    title: { display: true, text: impulseYTitle },
                                },
                            },
                            plugins: { title: { display: true, text: 'Detector-windowed Impulse Response' } },
                        },
                    });
                }
            });
        },

        _seriesColor(index) {
            const palette = window.PyPnmCharts?.seriesColors || [
                '#2563eb', '#dc3545', '#198754', '#f59e0b', '#8b5cf6',
                '#0891b2', '#d946ef', '#84cc16', '#0f766e', '#9f1239'
            ];
            return palette[index % palette.length];
        },

        _destroyChartSurface(key) {
            const chart = this.charts?.[key];
            if (!chart) return;
            try { chart.destroy(); } catch (_) {}
            delete this.charts[key];
        },

        _replaceChartSurface(key, canvasId, config) {
            this._destroyChartSurface(key);
            const canvas = document.getElementById(canvasId);
            if (!canvas || !window.Chart) return null;
            const chart = new Chart(canvas, config);
            this.charts[key] = chart;
            return chart;
        },

        _decimateExtrema(points, maxPoints = 5000) {
            if (!Array.isArray(points)) return [];
            if (points.length <= maxPoints) return points;
            const targetBuckets = Math.max(1, Math.floor((maxPoints - 2) / 2));
            const bucketSize = Math.ceil((points.length - 2) / targetBuckets);
            const sampled = [points[0]];
            for (let start = 1; start < points.length - 1; start += bucketSize) {
                const end = Math.min(points.length - 1, start + bucketSize);
                let minimum = points[start];
                let maximum = points[start];
                for (let index = start + 1; index < end; index++) {
                    const point = points[index];
                    if (point.y < minimum.y) minimum = point;
                    if (point.y > maximum.y) maximum = point;
                }
                if (minimum === maximum) sampled.push(minimum);
                else if (minimum.x <= maximum.x) sampled.push(minimum, maximum);
                else sampled.push(maximum, minimum);
            }
            if (sampled[sampled.length - 1] !== points[points.length - 1]) sampled.push(points[points.length - 1]);
            return sampled;
        },

        _numericPoints(xValues, yValues, xFallback = 0) {
            const count = Math.min(Array.isArray(xValues) ? xValues.length : 0, Array.isArray(yValues) ? yValues.length : 0);
            const points = [];
            if (count) {
                for (let index = 0; index < count; index++) {
                    const x = Number(xValues[index]);
                    const y = Number(yValues[index]);
                    if (Number.isFinite(x) && Number.isFinite(y)) points.push({ x, y });
                }
                return points;
            }
            (Array.isArray(yValues) ? yValues : []).forEach((value, index) => {
                const y = Number(value);
                if (Number.isFinite(y)) points.push({ x: index + xFallback, y });
            });
            return points;
        },

        _dbAxisPolicy(valueSets, { minimum = null, maximum = null, stepSize = null, targetDivisions = 8 } = {}) {
            // Choose one readable, snapped scale for every comparable series.
            // Inputs may be raw numeric arrays or Chart.js {x, y} point arrays;
            // only extrema are retained, so auxiliary memory remains constant.
            let observedMinimum = Number.POSITIVE_INFINITY;
            let observedMaximum = Number.NEGATIVE_INFINITY;
            for (const values of (valueSets || [])) {
                for (const value of (values || [])) {
                    const y = Number(value && typeof value === 'object' ? value.y : value);
                    if (!Number.isFinite(y)) continue;
                    observedMinimum = Math.min(observedMinimum, y);
                    observedMaximum = Math.max(observedMaximum, y);
                }
            }

            const fixedMinimum = minimum !== null && minimum !== undefined && Number.isFinite(Number(minimum))
                ? Number(minimum)
                : null;
            const fixedMaximum = maximum !== null && maximum !== undefined && Number.isFinite(Number(maximum))
                ? Number(maximum)
                : null;
            const fixedStep = stepSize !== null && stepSize !== undefined && Number(stepSize) > 0
                ? Number(stepSize)
                : null;
            let lower = fixedMinimum ?? observedMinimum;
            let upper = fixedMaximum ?? observedMaximum;
            if (!Number.isFinite(lower) || !Number.isFinite(upper)) {
                lower = -1;
                upper = 1;
            }
            if (upper < lower) [lower, upper] = [upper, lower];

            let resolvedStep = fixedStep;
            if (!resolvedStep) {
                const span = upper - lower;
                const rawStep = span > 0
                    ? span / Math.max(1, Number(targetDivisions) || 8)
                    : Math.max(Math.abs(lower), 1) / Math.max(1, Number(targetDivisions) || 8);
                const magnitude = 10 ** Math.floor(Math.log10(rawStep));
                const normalized = rawStep / magnitude;
                const niceMultiplier = normalized <= 1 ? 1 : (normalized <= 2 ? 2 : (normalized <= 5 ? 5 : 10));
                resolvedStep = niceMultiplier * magnitude;
            }

            const axisMinimum = fixedMinimum ?? Math.floor(lower / resolvedStep) * resolvedStep;
            let axisMaximum = fixedMaximum ?? Math.ceil(upper / resolvedStep) * resolvedStep;
            if (axisMaximum <= axisMinimum) axisMaximum = axisMinimum + resolvedStep;
            const dbPerDivision = Number(resolvedStep.toPrecision(12));
            return {
                dbPerDivision,
                yScale: {
                    min: Object.is(axisMinimum, -0) ? 0 : axisMinimum,
                    max: axisMaximum,
                    ticks: { stepSize: dbPerDivision, autoSkip: false },
                },
            };
        },

        _frequencyAxisPolicy(direction, pointSets) {
            // Keep comparable views stable across separate captures and page renders.
            const mhzPerDivision = direction === 'upstream' ? 10 : 20;
            let minimum = Number.POSITIVE_INFINITY;
            let maximum = Number.NEGATIVE_INFINITY;
            for (const points of (pointSets || [])) {
                for (const point of (points || [])) {
                    const x = Number(point?.x);
                    if (!Number.isFinite(x)) continue;
                    minimum = Math.min(minimum, x);
                    maximum = Math.max(maximum, x);
                }
            }
            const xScale = {
                ticks: { stepSize: mhzPerDivision, autoSkip: false },
            };
            if (Number.isFinite(minimum) && Number.isFinite(maximum)) {
                xScale.min = Math.floor(minimum / mhzPerDivision) * mhzPerDivision;
                xScale.max = Math.ceil(maximum / mhzPerDivision) * mhzPerDivision;
                if (xScale.max <= xScale.min) xScale.max = xScale.min + mhzPerDivision;
            }
            return {
                mhzPerDivision,
                xScale,
                title: `Frequency (MHz · ${mhzPerDivision} MHz/div)`,
            };
        },

        _renderQuantitativeChart(key, canvasId, datasets, { title, xTitle, yTitle, maxPoints = 5000, xScale = null, yScale = null } = {}) {
            const usable = (datasets || []).filter(dataset => Array.isArray(dataset.data) && dataset.data.length);
            if (!usable.length) {
                this._destroyChartSurface(key);
                return;
            }
            const displaySets = usable.map((dataset, index) => ({
                ...dataset,
                data: this._decimateExtrema(dataset.data, maxPoints),
                parsing: false,
                borderColor: dataset.borderColor || this._seriesColor(index),
                backgroundColor: dataset.backgroundColor || 'transparent',
                borderWidth: dataset.borderWidth || 1,
                pointRadius: dataset.pointRadius ?? 0,
                tension: 0,
            }));
            this._replaceChartSurface(key, canvasId, {
                type: 'line',
                data: { datasets: displaySets },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    parsing: false,
                    normalized: true,
                    interaction: { mode: 'nearest', axis: 'x', intersect: false },
                    plugins: {
                        title: { display: Boolean(title), text: title || '' },
                        tooltip: { callbacks: {
                            title: context => context.length ? `${Number(context[0].parsed.x).toFixed(3)} ${xTitle?.includes('MHz') ? 'MHz' : ''}`.trim() : '',
                            label: context => `${context.dataset.label}: ${Number(context.parsed.y).toFixed(2)}`,
                        }},
                    },
                    scales: {
                        x: { type: 'linear', ...(xScale || {}), title: { display: Boolean(xTitle), text: xTitle || '' } },
                        y: { ...(yScale || {}), title: { display: Boolean(yTitle), text: yTitle || '' } },
                    },
                },
            });
        },

        _rxmerCaptureDataset(capture, index = 0) {
            const values = capture?.values || [];
            const frequencies = capture?.frequencies_mhz || [];
            const points = this._numericPoints(frequencies, values, Number(capture?.first_active_subcarrier_index || 0));
            const mac = capture?.cm_mac_address || capture?.mac_address || this.selectedModem?.mac_address || `Capture ${index + 1}`;
            const preEq = capture?.preeq_enabled;
            return {
                label: `${mac}${preEq === undefined || preEq === null ? '' : ` · Pre-EQ ${preEq ? 'ON' : 'OFF'}`}`,
                data: points,
            };
        },

        renderUsRxmerChart() {
            const capture = this.usRxmerCaptures[this.usRxmerDisplayIndex]?.rxmer_data;
            const canvas = document.getElementById('usRxmerChart');
            const values = Array.isArray(capture?.values) ? capture.values : [];
            const frequencies = Array.isArray(capture?.frequencies_mhz) ? capture.frequencies_mhz : [];
            const firstIndex = Number(capture?.first_active_subcarrier_index || 0);
            if (!canvas || !values.length) return;

            const points = values
                .map((value, index) => ({
                    x: Number.isFinite(Number(frequencies[index]))
                        ? Number(frequencies[index])
                        : firstIndex + index,
                    y: Number(value),
                }))
                .filter(point => Number.isFinite(point.x) && Number.isFinite(point.y));
            if (!points.length) return;

            if (this.usRxmerChartInstance) this.usRxmerChartInstance.destroy();
            this.usRxmerChartInstance = new Chart(canvas.getContext('2d'), {
                type: 'line',
                data: {
                    datasets: [{
                        label: 'RxMER (dB)',
                        data: points,
                        parsing: false,
                        borderColor: '#0d6efd',
                        backgroundColor: 'rgba(13,110,253,0.08)',
                        borderWidth: 1,
                        pointRadius: 0,
                        fill: true,
                        tension: 0,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    interaction: { mode: 'nearest', axis: 'x', intersect: false },
                    plugins: {
                        title: { display: true, text: 'Upstream OFDMA RxMER' },
                    },
                    scales: {
                        x: {
                            type: 'linear',
                            title: {
                                display: true,
                                text: frequencies.length ? 'Frequency (MHz)' : 'Subcarrier',
                            },
                        },
                        y: {
                            title: { display: true, text: 'RxMER (dB)' },
                        },
                    },
                },
            });
        },

        _renderRxmerAnalysisSurface(key, canvasId, analysis, title) {
            const captures = Array.isArray(analysis?.captures) ? analysis.captures : [];
            this._renderQuantitativeChart(key, canvasId, captures.map((capture, index) => this._rxmerCaptureDataset(capture, index)), {
                title, xTitle: captures.some(capture => capture?.frequencies_mhz?.length) ? 'Frequency (MHz)' : 'Subcarrier', yTitle: 'RxMER (dB)'
            });
        },

        renderUsRxmerComparisonChart() {
            this._renderRxmerAnalysisSurface('surface-us-rxmer-comparison', 'usRxmerComparisonChart', this.usRxmerAnalysis, 'Pre-EQ Comparison');
        },

        renderManualFiberNodeChart() {
            this._renderRxmerAnalysisSurface('surface-manual-fn-rxmer', 'manualFiberNodeChart', this.fiberNodeAnalysis, 'Fiber Node RxMER Overlay');
        },

        renderBulkFiberNodeCharts() {
            this._renderRxmerAnalysisSurface('surface-bulk-fn-rxmer', 'bulkFiberNodeChart', this.fnScanResult, 'Fiber Node RxMER Overlay');
            const tapSeries = this.fnScanTapProfile?.series || [];
            const datasets = tapSeries.map(series => ({
                label: `${series.mac_address}${series.us_ifindex != null ? ` · Ch ${series.us_ifindex}` : ''}`,
                data: (series.points || []).filter(point => point.magnitude_db_relative != null && Number.isFinite(Number(point.magnitude_db_relative))).map(point => ({
                    x: Number(point.tap_offset), y: Number(point.magnitude_db_relative)
                })),
            }));
            this._renderQuantitativeChart('surface-fn-tap-profile', 'fnTapProfileChart', datasets, {
                title: 'Pre-EQ Tap Distance Profile', xTitle: 'Tap offset from main tap', yTitle: 'Magnitude relative to main tap (dB)', maxPoints: 1000
            });
        },

        renderDsOverlayChart() {
            const datasets = [];
            (this.dsScanResult?.modems || []).filter(modem => modem.success).forEach(modem => {
                (modem.channels || []).forEach(channel => {
                    const amplitudes = channel.amplitudes_db || [];
                    const center = Number(channel.center_freq_mhz);
                    const count = amplitudes.length;
                    const frequencies = Number.isFinite(center) && count > 1
                        ? amplitudes.map((_, index) => center - 96 + (192 * index / (count - 1)))
                        : [];
                    datasets.push({
                        label: `${modem.mac_address}${channel.channel_id != null ? ` · Ch ${channel.channel_id}` : ''}`,
                        data: this._numericPoints(frequencies, amplitudes),
                    });
                });
            });
            this._renderQuantitativeChart('surface-ds-overlay', 'dsOverlayChart', datasets, {
                title: 'DS Channel-Estimation Overlay', xTitle: 'Frequency (MHz)', yTitle: 'Amplitude (dB)'
            });
        },

        renderFullbandOverlayChart() {
            const datasets = (this.fbScanResult?.modems || []).filter(modem => modem.success).map(modem => ({
                label: modem.mac_address,
                data: this._numericPoints(modem.frequencies_mhz || [], modem.amplitudes_dbmv || []),
            }));
            let yMin = Infinity;
            let yMax = -Infinity;
            datasets.forEach(dataset => dataset.data.forEach(point => {
                yMin = Math.min(yMin, point.y);
                yMax = Math.max(yMax, point.y);
            }));
            if (!Number.isFinite(yMin) || !Number.isFinite(yMax)) {
                yMin = -60;
                yMax = 10;
            }
            (this.fbScanResult?.detections || []).slice(0, 40).forEach((detection, index) => {
                if (!['suckout', 'lte_ingress'].includes(detection.type)) return;
                const color = detection.type === 'suckout' ? '#dc3545' : '#f59e0b';
                const label = detection.type === 'suckout' ? 'Suckout boundary' : (detection.band || 'LTE boundary');
                [detection.freq_start_mhz, detection.freq_end_mhz].forEach((frequency, boundaryIndex) => {
                    const x = Number(frequency);
                    if (!Number.isFinite(x)) return;
                    datasets.push({
                        label: index === 0 && boundaryIndex === 0 ? label : `${label} ${index + 1}`,
                        data: [{ x, y: yMin }, { x, y: yMax }],
                        borderColor: color,
                        borderDash: detection.type === 'suckout' ? [5, 4] : [2, 4],
                        borderWidth: 1,
                        pointRadius: 0,
                    });
                });
            });
            this._renderQuantitativeChart('surface-fullband-overlay', 'fullbandOverlayChart', datasets, {
                title: 'DS Fullband Spectrum Overlay', xTitle: 'Frequency (MHz)', yTitle: 'Amplitude (dBmV)'
            });
        },

        downloadCanvasPng(canvasId, name) {
            window.PyPnmCharts?.downloadPng(document.getElementById(canvasId), name);
        },

        downloadArchivePlot(plot) {
            window.PyPnmCharts?.downloadBase64Png(plot?.data, plot?.filename || 'pypnm-archive-plot');
        },

        drawSpectrumCharts(data) {
            const container = document.getElementById('measurement-charts-container');
            const analyses = Array.isArray(data?.analysis) ? data.analysis : [];
            let rendered = 0;

            analyses.forEach((analysis, analysisIndex) => {
                const signal = analysis.signal_analysis || {};
                const frequencies = Array.isArray(signal.frequencies) ? signal.frequencies : [];
                const magnitudes = Array.isArray(signal.magnitudes) ? signal.magnitudes : [];
                const count = Math.min(frequencies.length, magnitudes.length);
                if (!count) return;

                const rawPoints = [];
                for (let index = 0; index < count; index++) {
                    const point = { x: Number(frequencies[index]) / 1e6, y: Number(magnitudes[index]) };
                    if (Number.isFinite(point.x) && Number.isFinite(point.y)) rawPoints.push(point);
                }
                if (!rawPoints.length) return;
                const displayPoints = this._decimateExtrema(rawPoints, 5000);

                const averageValues = signal.window_average?.magnitudes || [];
                const averagePoints = [];
                for (let index = 0; index < Math.min(frequencies.length, averageValues.length); index++) {
                    const point = { x: Number(frequencies[index]) / 1e6, y: Number(averageValues[index]) };
                    if (Number.isFinite(point.x) && Number.isFinite(point.y)) averagePoints.push(point);
                }
                const displayAverage = this._decimateExtrema(averagePoints, 5000);

                const capture = analysis.capture_parameters || {};
                const startMhz = Number.isFinite(Number(capture.first_segment_center_freq))
                    ? Number(capture.first_segment_center_freq) / 1e6
                    : rawPoints[0].x;
                const endMhz = Number.isFinite(Number(capture.last_segment_center_freq))
                    ? Number(capture.last_segment_center_freq) / 1e6
                    : rawPoints[rawPoints.length - 1].x;
                const channelLabel = analysis.channel_id !== undefined ? ` · Ch ${analysis.channel_id}` : '';

                const block = document.createElement('div');
                block.className = 'mb-4';
                const heading = document.createElement('div');
                heading.className = 'd-flex justify-content-between align-items-center flex-wrap gap-2 mb-2';
                const title = document.createElement('h6');
                title.className = 'mb-0';
                title.textContent = `Full Spectrum Analysis${channelLabel} (${startMhz.toFixed(1)}–${endMhz.toFixed(1)} MHz)`;
                const detail = document.createElement('small');
                detail.className = 'text-muted';
                detail.textContent = `${displayPoints.length} extrema-preserved display points · ${rawPoints.length} total`;
                heading.append(title, detail);
                const chartWrap = document.createElement('div');
                chartWrap.style.height = '340px';
                const canvas = document.createElement('canvas');
                chartWrap.appendChild(canvas);
                block.append(heading, chartWrap);
                container.appendChild(block);

                new Chart(canvas.getContext('2d'), {
                    type: 'line',
                    data: { datasets: [
                        {
                            label: 'Magnitude (dB)', data: displayPoints, parsing: false,
                            borderColor: '#0d6efd', backgroundColor: 'rgba(13,110,253,0.08)',
                            borderWidth: 1, pointRadius: 0, tension: 0,
                        },
                        ...(displayAverage.length ? [{
                            label: `Moving average (${signal.window_average?.points ?? '?'} points)`,
                            data: displayAverage, parsing: false, borderColor: '#dc3545',
                            borderWidth: 1, pointRadius: 0, tension: 0,
                        }] : []),
                    ]},
                    options: {
                        responsive: true, maintainAspectRatio: false, animation: false, parsing: false,
                        interaction: { mode: 'nearest', axis: 'x', intersect: false },
                        plugins: {
                            title: { display: true, text: `Spectrum Analyzer${channelLabel}` },
                            tooltip: { callbacks: {
                                title: context => `${Number(context[0].parsed.x).toFixed(3)} MHz`,
                                label: context => `${context.dataset.label}: ${Number(context.parsed.y).toFixed(2)}`,
                            }},
                        },
                        scales: {
                            x: { type: 'linear', title: { display: true, text: 'Frequency (MHz)' } },
                            y: { title: { display: true, text: 'Magnitude (dB)' } },
                        },
                    },
                });
                rendered += 1;
            });

            if (!rendered) {
                container.innerHTML = '<div class="alert alert-warning"><i class="bi bi-exclamation-triangle me-2"></i>No spectrum analysis samples were returned. Raw Data remains available for schema inspection.</div>';
            }
        },
        
        // ── Utility: simple linear-regression fitted values ─────────────────
        _linRegY(xArr, yArr) {
            const n = xArr.length;
            if (n < 2) return yArr.slice();
            const sx = xArr.reduce((a, v) => a + v, 0);
            const sy = yArr.reduce((a, v) => a + v, 0);
            const sxy = xArr.reduce((a, v, i) => a + v * yArr[i], 0);
            const sxx = xArr.reduce((a, v) => a + v * v, 0);
            const slope = (n * sxy - sx * sy) / (n * sxx - sx * sx || 1);
            const intercept = (sy - slope * sx) / n;
            return xArr.map(x => slope * x + intercept);
        },

        // ── Utility: detect suckout groups ───────────────────────────────────
        // Returns [{freq_mhz, depth_db, width_mhz, start_mhz, end_mhz, amp_db}]
        _detectSuckouts(freqsMhz, ampDb, regY, thresholdDb) {
            const delta = ampDb.map((a, i) => a - regY[i]);
            const suckouts = [];
            let inSuckout = false, start = 0, minDelta = 0, minIdx = 0;
            for (let i = 0; i <= delta.length; i++) {
                const below = i < delta.length && delta[i] < -thresholdDb;
                if (below && !inSuckout) { inSuckout = true; start = i; minDelta = delta[i]; minIdx = i; }
                else if (below && inSuckout && delta[i] < minDelta) { minDelta = delta[i]; minIdx = i; }
                else if (!below && inSuckout) {
                    inSuckout = false;
                    const end = i - 1;
                    suckouts.push({
                        freq_mhz:  parseFloat(freqsMhz[minIdx].toFixed(1)),
                        amp_db:    parseFloat(ampDb[minIdx].toFixed(1)),
                        depth_db:  parseFloat((-minDelta).toFixed(1)),
                        start_mhz: parseFloat(freqsMhz[start].toFixed(1)),
                        end_mhz:   parseFloat(freqsMhz[end].toFixed(1)),
                        width_mhz: parseFloat((freqsMhz[end] - freqsMhz[start]).toFixed(1)),
                        idx:       minIdx,
                    });
                }
            }
            return suckouts;
        },

        drawChannelEstimationCharts(channels) {
            const container = document.getElementById('measurement-charts-container');
            if (!channels || !channels.length) {
                container.innerHTML = '<div class="alert alert-warning">No channel estimation data returned.</div>';
                return;
            }

            let rendered = 0;
            for (const ch of channels) {
                const cv = ch.carrier_values || {};
                const freqsHz = Array.isArray(cv.frequency) ? cv.frequency : [];
                const magsLin = Array.isArray(cv.magnitudes) ? cv.magnitudes : [];
                const gdInfo = cv.group_delay || {};
                const gdValues = Array.isArray(gdInfo.magnitude) ? gdInfo.magnitude : [];
                const gdUnit = gdInfo.group_delay_unit || 'reported unit';
                const carrierCount = Math.min(freqsHz.length, magsLin.length);
                if (!carrierCount) continue;

                const freqsMhz = freqsHz.slice(0, carrierCount).map(f => Number(f) / 1e6);
                // magnitudes from PyPNM are already in dB (10*log10(|z|^2)).
                // If values look linear (all positive and < 10), convert to dB;
                // otherwise assume they're already dB.
                const rawMags = magsLin.slice(0, carrierCount).map(m => Number(m));
                const looksLinear = rawMags.length > 0 && rawMags.every(m => m >= 0 && m < 10);
                const ampDb = looksLinear
                    ? rawMags.map(m => 20 * Math.log10(Math.max(m, 1e-12)))
                    : rawMags;
                const gd = gdValues.slice(0, carrierCount).map(Number);
                const regY     = this._linRegY(freqsMhz, ampDb);
                const suckouts = this._detectSuckouts(freqsMhz, ampDb, regY, 3.0);

                const cid     = ch.channel_id ?? 0;
                const chanDiv = document.createElement('div');
                chanDiv.className = 'mb-4';
                chanDiv.innerHTML = `
                    <h6 class="text-primary"><i class="bi bi-soundwave me-1"></i>Channel ${cid} — DS OFDM Amplitude Profile</h6>
                    <canvas id="chanest-amp-${cid}" height="220"></canvas>
                    ${gd.length ? `<h6 class="text-success mt-3"><i class="bi bi-clock me-1"></i>Channel ${cid} — Group Delay</h6><canvas id="chanest-gd-${cid}" height="140"></canvas>` : ''}
                    ${suckouts.length ? `
                    <div class="alert alert-warning py-2 mt-2 mb-0">
                        <strong><i class="bi bi-exclamation-triangle me-1"></i>${suckouts.length} suckout${suckouts.length > 1 ? 's' : ''} detected (≥3 dB below trend):</strong>
                        <table class="table table-sm table-bordered mb-0 mt-1">
                            <thead><tr><th>Freq (MHz)</th><th>Depth (dB)</th><th>Width (MHz)</th><th>Range</th></tr></thead>
                            <tbody>${suckouts.map(s =>
                                `<tr class="table-warning">
                                    <td><strong>${s.freq_mhz}</strong></td>
                                    <td class="text-danger fw-bold">-${s.depth_db}</td>
                                    <td>${s.width_mhz}</td>
                                    <td class="text-muted small">${s.start_mhz}–${s.end_mhz} MHz</td>
                                </tr>`).join('')}
                            </tbody></table>
                    </div>` : '<div class="alert alert-success py-1 mt-2 mb-0"><i class="bi bi-check-circle me-1"></i>No suckouts detected ≥3 dB below trend</div>'}
                `;
                container.appendChild(chanDiv);
                rendered += 1;

                // ── Amplitude chart ──────────────────────────────────────────
                const ampCtx = chanDiv.querySelector(`#chanest-amp-${cid}`);
                const ampPoints = freqsMhz.map((frequency, index) => ({ x: frequency, y: ampDb[index] }));
                const regressionPoints = freqsMhz.map((frequency, index) => ({ x: frequency, y: regY[index] }));

                new Chart(ampCtx.getContext('2d'), {
                    type: 'line',
                    data: {
                        datasets: [
                            {
                                label: 'Amplitude (dB)',
                                data: ampPoints,
                                parsing: false,
                                borderColor: '#0d6efd', borderWidth: 1,
                                pointRadius: 0, tension: 0,
                                fill: { target: '-1', above: 'rgba(13,110,253,0.08)' },
                            },
                            {
                                label: 'Trend (regression)',
                                data: regressionPoints,
                                parsing: false,
                                borderColor: '#adb5bd', borderWidth: 1,
                                borderDash: [5, 5], pointRadius: 0, tension: 0,
                            },
                            ...(suckouts.length ? [{
                                label: 'Suckout peak',
                                data: suckouts.map(suckout => ({ x: freqsMhz[suckout.idx], y: ampDb[suckout.idx] })),
                                parsing: false,
                                borderColor: 'transparent',
                                backgroundColor: '#dc3545',
                                pointRadius: 7,
                                pointStyle: 'triangle',
                                showLine: false,
                            }] : []),
                        ],
                    },
                    options: {
                        responsive: true,
                        animation: false,
                        parsing: false,
                        interaction: { mode: 'nearest', axis: 'x', intersect: false },
                        scales: {
                            x: { type: 'linear', title: { display: true, text: 'Frequency (MHz)' }, ticks: { maxTicksLimit: 14 } },
                            y: { title: { display: true, text: 'Amplitude (dB)' } },
                        },
                        plugins: {
                            title:  { display: true, text: `DS OFDM Channel Estimation · Ch ${cid} (${freqsMhz[0].toFixed(0)}–${freqsMhz.at(-1).toFixed(0)} MHz)` },
                            legend: { position: 'top', labels: { boxWidth: 12, font: { size: 11 } } },
                        },
                    },
                });

                // ── Group delay chart ────────────────────────────────────────
                if (gd.length) {
                    const gdCtx = chanDiv.querySelector(`#chanest-gd-${cid}`);
                    const gdPoints = freqsMhz.slice(0, gd.length).map((frequency, index) => ({ x: frequency, y: gd[index] }));
                    new Chart(gdCtx.getContext('2d'), {
                        type: 'line',
                        data: {
                            datasets: [{
                                label: `Group delay (${gdUnit})`,
                                data: gdPoints,
                                parsing: false,
                                borderColor: '#198754', borderWidth: 1,
                                pointRadius: 0, tension: 0,
                            }],
                        },
                        options: {
                            responsive: true,
                            animation: false,
                            parsing: false,
                            interaction: { mode: 'nearest', axis: 'x', intersect: false },
                            scales: {
                                x: { type: 'linear', title: { display: true, text: 'Frequency (MHz)' }, ticks: { maxTicksLimit: 14 } },
                                y: { title: { display: true, text: `Group delay (${gdUnit})` } },
                            },
                            plugins: {
                                title: { display: true, text: `DS OFDM Group Delay · Ch ${cid}` },
                                legend: { display: false },
                            },
                        },
                    });
                }
            }

            if (!rendered) {
                container.innerHTML = '<div class="alert alert-warning"><i class="bi bi-exclamation-triangle me-2"></i>No usable channel-estimation carrier data was returned. Raw Data remains available for schema inspection.</div>';
            }
        },
        
        drawModulationProfileCharts(data) {
            const container = document.getElementById('measurement-charts-container');
            const profiles = data.profiles || [];
            let rendered = 0;

            profiles.forEach(profile => {
                const carriers = (profile.carriers || []).filter(item => Number.isFinite(Number(item.frequency)));
                if (!carriers.length) return;

                const usesFrequency = carriers.some(item => Number(item.frequency) > 1e6);
                const points = carriers.map((item, index) => {
                    const text = String(item.modulation ?? '').toLowerCase();
                    const match = text.match(/(?:qam[_-]?)?(\d+)/);
                    const order = Number.isFinite(Number(item.modulation))
                        ? Number(item.modulation)
                        : (match ? Number(match[1]) : null);
                    return {
                        x: usesFrequency ? Number(item.frequency) / 1e6 : index,
                        y: order,
                        modulation: item.modulation ?? 'unknown',
                        shannonMinMer: Number(item.shannonMinMer),
                    };
                });

                const block = document.createElement('div');
                block.className = 'mb-4';
                const heading = document.createElement('h6');
                heading.textContent = `Channel ${profile.channelId ?? '?'} — Profile ${profile.profileId ?? '?'}`;
                const chartWrap = document.createElement('div');
                chartWrap.style.height = '300px';
                const canvas = document.createElement('canvas');
                chartWrap.appendChild(canvas);
                block.append(heading, chartWrap);
                container.appendChild(block);

                const shannonPoints = points.filter(point => Number.isFinite(point.shannonMinMer));
                new Chart(canvas.getContext('2d'), {
                    type: 'line',
                    data: { datasets: [
                        {
                            label: 'QAM order', data: points, parsing: false,
                            borderColor: '#0d6efd', backgroundColor: 'rgba(13,110,253,0.15)',
                            borderWidth: 1, pointRadius: 0, stepped: true, spanGaps: false,
                            yAxisID: 'y',
                        },
                        ...(shannonPoints.length ? [{
                            label: 'Shannon minimum MER (dB)',
                            data: shannonPoints.map(point => ({ x: point.x, y: point.shannonMinMer })),
                            parsing: false, borderColor: '#dc3545', borderWidth: 1,
                            pointRadius: 0, yAxisID: 'yMer',
                        }] : []),
                    ]},
                    options: {
                        responsive: true, maintainAspectRatio: false, animation: false,
                        interaction: { mode: 'nearest', axis: 'x', intersect: false },
                        plugins: {
                            title: { display: true, text: `DS OFDM Modulation Profile · Ch ${profile.channelId ?? '?'} · Profile ${profile.profileId ?? '?'}` },
                            tooltip: { callbacks: { label: context => {
                                if (context.datasetIndex === 0) return `Modulation: ${context.raw.modulation}`;
                                return `Shannon minimum MER: ${Number(context.parsed.y).toFixed(2)} dB`;
                            }}},
                        },
                        scales: {
                            x: { type: 'linear', title: { display: true, text: usesFrequency ? 'Frequency (MHz)' : 'Subcarrier index' } },
                            y: { position: 'left', beginAtZero: true, title: { display: true, text: 'QAM order' } },
                            yMer: { position: 'right', display: shannonPoints.length > 0, grid: { drawOnChartArea: false }, title: { display: true, text: 'Minimum MER (dB)' } },
                        },
                    },
                });
                rendered += 1;
            });

            if (!rendered) {
                container.innerHTML = '<div class="alert alert-warning"><i class="bi bi-exclamation-triangle me-2"></i>No modulation-profile carrier data was returned. Raw Data remains available for schema inspection.</div>';
            }
        },

        drawFecSummaryCharts(data) {
            const container = document.getElementById('measurement-charts-container');
            const series = data.series || [];
            let rendered = 0;

            series.forEach(item => {
                const count = Math.min(item.total.length, item.corrected.length, item.uncorrected.length);
                if (!count) return;
                const labels = Array.from({ length: count }, (_, index) => {
                    const timestamp = item.timestamps[index];
                    const numeric = Number(timestamp);
                    return Number.isFinite(numeric) && numeric > 0
                        ? new Date(numeric * 1000).toLocaleString()
                        : (timestamp || `Sample ${index + 1}`);
                });

                const block = document.createElement('div');
                block.className = 'mb-4';
                const heading = document.createElement('h6');
                heading.textContent = `Channel ${item.channelId ?? '?'} — Profile ${item.profileId ?? '?'}`;
                const chartWrap = document.createElement('div');
                chartWrap.style.height = '300px';
                const canvas = document.createElement('canvas');
                chartWrap.appendChild(canvas);
                block.append(heading, chartWrap);
                container.appendChild(block);

                new Chart(canvas.getContext('2d'), {
                    type: 'line',
                    data: { labels, datasets: [
                        { label: 'Total codewords', data: item.total.slice(0, count), borderColor: '#0d6efd', backgroundColor: 'rgba(13,110,253,0.1)', borderWidth: 1, pointRadius: count === 1 ? 4 : 2, yAxisID: 'yTotal' },
                        { label: 'Corrected', data: item.corrected.slice(0, count), borderColor: '#fd7e14', backgroundColor: 'rgba(253,126,20,0.1)', borderWidth: 1, pointRadius: count === 1 ? 4 : 2, yAxisID: 'yErrors' },
                        { label: 'Uncorrectable', data: item.uncorrected.slice(0, count), borderColor: '#dc3545', backgroundColor: 'rgba(220,53,69,0.1)', borderWidth: 1, pointRadius: count === 1 ? 4 : 2, yAxisID: 'yErrors' },
                    ]},
                    options: {
                        responsive: true, maintainAspectRatio: false, animation: false,
                        interaction: { mode: 'index', intersect: false },
                        plugins: { title: { display: true, text: `FEC Codewords per Reported Sample · Ch ${item.channelId ?? '?'} · Profile ${item.profileId ?? '?'}` } },
                        scales: {
                            x: { title: { display: true, text: 'Capture timestamp' } },
                            yTotal: { position: 'left', beginAtZero: true, title: { display: true, text: 'Total codewords' } },
                            yErrors: { position: 'right', beginAtZero: true, grid: { drawOnChartArea: false }, title: { display: true, text: 'Corrected / uncorrectable' } },
                        },
                    },
                });
                rendered += 1;
            });

            if (!rendered) {
                container.innerHTML = '<div class="alert alert-warning"><i class="bi bi-exclamation-triangle me-2"></i>No aligned FEC codeword samples were returned. Raw Data remains available for schema inspection.</div>';
            }
        },

        drawHistogramCharts(data) {
            const container = document.getElementById('measurement-charts-container');
            const histograms = data.histograms || [];
            let rendered = 0;

            histograms.forEach(histogram => {
                const bins = histogram.bins || [];
                if (!bins.length) return;
                const labels = bins.map((bin, index) => bin.index ?? bin.power_level ?? bin.bin ?? index);
                const counts = bins.map(bin => Number(bin.count ?? bin.value ?? 0));

                const block = document.createElement('div');
                block.className = 'mb-4';
                const heading = document.createElement('h6');
                heading.textContent = `Channel ${histogram.channelId ?? '?'} — ${bins.length} histogram bins`;
                const detail = document.createElement('small');
                detail.className = 'text-muted d-block mb-2';
                detail.textContent = `Symmetry: ${histogram.symmetry ?? 'not reported'} · dwell samples: ${(histogram.dwellCounts || []).length}`;
                const chartWrap = document.createElement('div');
                chartWrap.style.height = '300px';
                const canvas = document.createElement('canvas');
                chartWrap.appendChild(canvas);
                block.append(heading, detail, chartWrap);
                container.appendChild(block);

                new Chart(canvas.getContext('2d'), {
                    type: 'bar',
                    data: { labels, datasets: [{
                        label: 'Hit count', data: counts,
                        backgroundColor: 'rgba(111,66,193,0.55)', borderColor: '#6f42c1', borderWidth: 1,
                    }]},
                    options: {
                        responsive: true, maintainAspectRatio: false, animation: false,
                        plugins: { title: { display: true, text: `DS Histogram · Ch ${histogram.channelId ?? '?'}` }, legend: { display: false } },
                        scales: {
                            x: { title: { display: true, text: 'Histogram bin index' }, ticks: { maxTicksLimit: 20 } },
                            y: { beginAtZero: true, title: { display: true, text: 'Hit count' } },
                        },
                    },
                });
                rendered += 1;
            });

            if (!rendered) {
                container.innerHTML = '<div class="alert alert-warning"><i class="bi bi-exclamation-triangle me-2"></i>No histogram hit-count data was returned. Raw Data remains available for schema inspection.</div>';
            }
        },

        drawConstellationCharts(data) {
            const container = document.getElementById('measurement-charts-container');
            const constellations = data.constellations || [];
            let rendered = 0;

            const toPoints = pairs => (pairs || []).map(pair => ({
                x: Number(pair?.[0]), y: Number(pair?.[1]),
            })).filter(point => Number.isFinite(point.x) && Number.isFinite(point.y));

            constellations.forEach(item => {
                const soft = toPoints(item.soft);
                const hard = toPoints(item.hard);
                if (!soft.length && !hard.length) return;

                const block = document.createElement('div');
                block.className = 'mb-4';
                const heading = document.createElement('h6');
                heading.textContent = `Channel ${item.channelId ?? '?'}${item.modulationOrder ? ` — ${item.modulationOrder}` : ''}`;
                const chartWrap = document.createElement('div');
                chartWrap.style.height = '420px';
                const canvas = document.createElement('canvas');
                chartWrap.appendChild(canvas);
                block.append(heading, chartWrap);
                container.appendChild(block);

                new Chart(canvas.getContext('2d'), {
                    type: 'scatter',
                    data: { datasets: [
                        ...(soft.length ? [{ label: 'Received symbols (soft)', data: soft, parsing: false, backgroundColor: 'rgba(13,110,253,0.35)', pointRadius: 1.5 }] : []),
                        ...(hard.length ? [{ label: 'Reference decisions (hard)', data: hard, parsing: false, borderColor: 'rgba(220,53,69,0.7)', backgroundColor: 'rgba(220,53,69,0.15)', pointStyle: 'crossRot', pointRadius: 3 }] : []),
                    ]},
                    options: {
                        responsive: true, maintainAspectRatio: false, animation: false,
                        plugins: { title: { display: true, text: `IQ Constellation · Ch ${item.channelId ?? '?'}` } },
                        scales: {
                            x: { type: 'linear', title: { display: true, text: 'I (in-phase)' } },
                            y: { type: 'linear', title: { display: true, text: 'Q (quadrature)' } },
                        },
                    },
                });
                rendered += 1;
            });

            if (!rendered) {
                container.innerHTML = '<div class="alert alert-warning"><i class="bi bi-exclamation-triangle me-2"></i>No constellation IQ samples were returned. Raw Data remains available for schema inspection.</div>';
            }
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
                            title: { display: true, text: 'Downstream Channel Power (dBmV)' }
                        },
                        scales: {
                            x: { title: { display: true, text: 'Frequency (MHz)' } },
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
        
        drawRxmerCharts(data) {
            const container = document.getElementById('measurement-charts-container');
            const channels = data.channels || [];
            let rendered = 0;

            channels.forEach(channel => {
                const count = Math.min(channel.indices.length, channel.magnitudes.length);
                if (!count) return;
                const finiteMagnitudes = channel.magnitudes.slice(0, count).filter(Number.isFinite);
                if (!finiteMagnitudes.length) return;

                const normalStatusEntry = Object.entries(channel.statusMap || {}).find(([name, value]) =>
                    name.toLowerCase().includes('normal') || String(value).toLowerCase().includes('normal')
                );
                const normalStatus = normalStatusEntry
                    ? (Number.isFinite(Number(normalStatusEntry[1])) ? Number(normalStatusEntry[1]) : Number(normalStatusEntry[0]))
                    : 2;
                const finiteSamples = channel.magnitudes.slice(0, count)
                    .map((value, index) => ({ value, status: channel.statuses[index] }))
                    .filter(sample => Number.isFinite(sample.value));
                const normalSamples = channel.statuses.length
                    ? finiteSamples.filter(sample => sample.status === normalStatus)
                    : finiteSamples;
                const values = (normalSamples.length ? normalSamples : finiteSamples).map(sample => sample.value);
                const average = values.reduce((sum, value) => sum + value, 0) / values.length;
                const minimum = Math.min(...values);
                const maximum = Math.max(...values);
                const deviation = Math.sqrt(values.reduce((sum, value) => sum + ((value - average) ** 2), 0) / values.length);

                const points = [];
                const flagged = [];
                for (let index = 0; index < count; index++) {
                    const point = {
                        x: Number(channel.indices[index]),
                        y: Number(channel.magnitudes[index]),
                        frequency: channel.frequencies[index],
                        status: channel.statuses[index],
                    };
                    if (!Number.isFinite(point.x) || !Number.isFinite(point.y)) continue;
                    points.push(point);
                    if (Number.isFinite(point.status) && point.status !== normalStatus) flagged.push(point);
                }

                const block = document.createElement('div');
                block.className = 'mb-4 border rounded p-3';
                const heading = document.createElement('h6');
                heading.textContent = `DS OFDM RxMER · Channel ${channel.channelId ?? '?'}`;
                const summary = document.createElement('div');
                summary.className = 'row g-2 mb-3';
                [
                    ['Average MER', average], ['Minimum MER', minimum],
                    ['Maximum MER', maximum], ['Std deviation', deviation],
                ].forEach(([label, value]) => {
                    const column = document.createElement('div');
                    column.className = 'col-6 col-lg-3';
                    const card = document.createElement('div');
                    card.className = 'bg-light rounded p-2 text-center';
                    const labelNode = document.createElement('small');
                    labelNode.className = 'text-muted d-block';
                    labelNode.textContent = label;
                    const valueNode = document.createElement('strong');
                    valueNode.textContent = `${Number(value).toFixed(2)} dB`;
                    card.append(labelNode, valueNode);
                    column.appendChild(card);
                    summary.appendChild(column);
                });
                const chartWrap = document.createElement('div');
                chartWrap.style.height = '320px';
                const canvas = document.createElement('canvas');
                chartWrap.appendChild(canvas);
                block.append(heading, summary, chartWrap);
                container.appendChild(block);

                new Chart(canvas.getContext('2d'), {
                    type: 'line',
                    data: { datasets: [
                        {
                            label: 'RxMER (dB)', data: points, parsing: false,
                            borderColor: '#0d6efd', backgroundColor: 'rgba(13,110,253,0.08)',
                            borderWidth: 1, pointRadius: 0, fill: true, tension: 0,
                        },
                        ...(flagged.length ? [{
                            label: 'Non-normal carrier', data: flagged, parsing: false,
                            showLine: false, pointRadius: 3, pointStyle: 'triangle', backgroundColor: '#dc3545',
                        }] : []),
                    ]},
                    options: {
                        responsive: true, maintainAspectRatio: false, animation: false,
                        interaction: { mode: 'nearest', axis: 'x', intersect: false },
                        plugins: {
                            title: { display: true, text: `RxMER per Subcarrier · Ch ${channel.channelId ?? '?'}` },
                            tooltip: { callbacks: { afterLabel: context => {
                                const frequency = Number(context.raw.frequency);
                                return Number.isFinite(frequency) ? `Frequency: ${(frequency / 1e6).toFixed(3)} MHz` : '';
                            }}},
                        },
                        scales: {
                            x: { type: 'linear', title: { display: true, text: 'Subcarrier index' } },
                            y: { suggestedMin: 25, suggestedMax: 50, title: { display: true, text: 'MER (dB)' } },
                        },
                    },
                });
                rendered += 1;
            });

            if (!rendered) {
                container.innerHTML = '<div class="alert alert-warning"><i class="bi bi-exclamation-triangle me-2"></i>No RxMER carrier values were returned. Raw Data remains available for schema inspection.</div>';
            }
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
                    plugins: { legend: { position: 'top' }, title: { display: true, text: 'Downstream — Power & MER by Frequency' } },
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
                    plugins: { legend: { display: false }, title: { display: true, text: 'Upstream TX Power (dBmV)' } },
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
        
        drawPreEqCharts(data) {
            const container = document.getElementById('measurement-charts-container');
            const channels = data.channels || [];
            let rendered = 0;

            channels.forEach(channel => {
                const carrier = channel.carrier_values || {};
                const frequencies = Array.isArray(carrier.frequency) ? carrier.frequency.map(Number) : [];
                const magnitudes = Array.isArray(carrier.magnitudes) ? carrier.magnitudes.map(Number) : [];
                const groupDelayInfo = carrier.group_delay || {};
                const groupDelay = Array.isArray(groupDelayInfo.magnitude) ? groupDelayInfo.magnitude.map(Number) : [];
                const groupDelayUnit = groupDelayInfo.group_delay_unit || 'reported unit';
                const count = Math.min(frequencies.length, magnitudes.length);
                if (!count) return;

                const responsePoints = [];
                const delayPoints = [];
                for (let index = 0; index < count; index++) {
                    const frequencyMhz = frequencies[index] / 1e6;
                    const magnitudeDb = 20 * Math.log10(Math.max(Math.abs(magnitudes[index]), 1e-12));
                    if (Number.isFinite(frequencyMhz) && Number.isFinite(magnitudeDb)) {
                        responsePoints.push({ x: frequencyMhz, y: magnitudeDb });
                    }
                    if (index < groupDelay.length && Number.isFinite(groupDelay[index])) {
                        delayPoints.push({ x: frequencyMhz, y: groupDelay[index] });
                    }
                }

                const block = document.createElement('div');
                block.className = 'mb-4 border rounded p-3';
                const heading = document.createElement('h6');
                heading.textContent = `US OFDMA Pre-equalizer Carrier Response · Channel ${channel.channel_id ?? '?'}`;
                const detail = document.createElement('small');
                detail.className = 'text-muted d-block mb-2';
                detail.textContent = `${count} carrier coefficients · frequency-domain magnitude (not time-domain tap magnitude)`;
                const responseWrap = document.createElement('div');
                responseWrap.style.height = '300px';
                const responseCanvas = document.createElement('canvas');
                responseWrap.appendChild(responseCanvas);
                block.append(heading, detail, responseWrap);

                let delayCanvas = null;
                if (delayPoints.length) {
                    const delayHeading = document.createElement('h6');
                    delayHeading.className = 'mt-3';
                    delayHeading.textContent = `Group Delay (${groupDelayUnit})`;
                    const delayWrap = document.createElement('div');
                    delayWrap.style.height = '220px';
                    delayCanvas = document.createElement('canvas');
                    delayWrap.appendChild(delayCanvas);
                    block.append(delayHeading, delayWrap);
                }
                container.appendChild(block);

                const commonOptions = {
                    responsive: true, maintainAspectRatio: false, animation: false, parsing: false,
                    interaction: { mode: 'nearest', axis: 'x', intersect: false },
                };
                new Chart(responseCanvas.getContext('2d'), {
                    type: 'line',
                    data: { datasets: [{
                        label: 'Coefficient magnitude (dB)', data: responsePoints,
                        borderColor: '#6f42c1', backgroundColor: 'rgba(111,66,193,0.08)',
                        borderWidth: 1, pointRadius: 0, fill: true,
                    }]},
                    options: {
                        ...commonOptions,
                        plugins: { title: { display: true, text: `US OFDMA Pre-equalizer Frequency Response · Ch ${channel.channel_id ?? '?'}` }, legend: { display: false } },
                        scales: {
                            x: { type: 'linear', title: { display: true, text: 'Frequency (MHz)' } },
                            y: { title: { display: true, text: 'Magnitude (dB)' } },
                        },
                    },
                });

                if (delayCanvas) {
                    new Chart(delayCanvas.getContext('2d'), {
                        type: 'line',
                        data: { datasets: [{ label: `Group delay (${groupDelayUnit})`, data: delayPoints, borderColor: '#198754', borderWidth: 1, pointRadius: 0 }] },
                        options: {
                            ...commonOptions,
                            plugins: { title: { display: true, text: `US OFDMA Group Delay · Ch ${channel.channel_id ?? '?'}` }, legend: { display: false } },
                            scales: {
                                x: { type: 'linear', title: { display: true, text: 'Frequency (MHz)' } },
                                y: { title: { display: true, text: `Group delay (${groupDelayUnit})` } },
                            },
                        },
                    });
                }
                rendered += 1;
            });

            if (!rendered) {
                container.innerHTML = '<div class="alert alert-warning"><i class="bi bi-exclamation-triangle me-2"></i>No upstream pre-equalization carrier response was returned. Raw Data remains available for schema inspection.</div>';
            }
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
